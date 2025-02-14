"""
use to visualize like zebrapose
"""
import os
import sys

sys.path.insert(0, os.getcwd())
cur_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(cur_dir, "../../"))  # add project directory to sys.path

import argparse
from tqdm import tqdm
import numpy as np

import torch
from mmcv import Config
from bop_toolkit_lib import inout

from core.symn.MetaInfo import MetaInfo
from core.symn.datasets.BOPDataset_utils import build_BOP_test_dataset, batch_data_test
from core.symn.models.SymNetLightning import build_model
from lib.utils.time_utils import get_time_str, add_timing_to_list
from core.symn.utils.image import grid_show
from core.symn.utils.visualize_utils import *
from core.symn.utils.renderer import ObjCoordRenderer
from core.symn.utils.obj import load_objs


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--eval_folder", default="output/SymNet_ycbv_obj13_20230531_164919")
    parser.add_argument("--debug", action="store_true")
    parser.add_argument('--device', default='cuda:0')
    parser.add_argument("--ckpt", default="all", help="ckpt name to be evaluated")
    parser.add_argument("--visualize", default=True)
    parser.add_argument("--scene_id", default=53)
    parser.add_argument("--image_id", default=550)

    args = parser.parse_args()
    # parse --eval_folder, generate args.config_file
    assert args.eval_folder
    for file in os.listdir(args.eval_folder):
        if os.path.splitext(file)[1] == '.py':
            args.config_file = os.path.join(args.eval_folder, file)

    cfg = Config.fromfile(args.config_file)
    # parse --ckpt, generate args.ckpt, do not use ckpt_for_last now
    ckpt = list()
    for file in os.listdir(args.eval_folder):
        if os.path.splitext(file)[1] == '.ckpt':
            ckpt.append(file)
    if args.ckpt == "all":
        args.ckpt = ckpt
    else:
        assert args.ckpt in ckpt
        args.ckpt = list(args.ckpt)
    # parse --debug
    cfg.DEBUG = args.debug
    # parse device
    device = torch.device(args.device)
    # get info used in calculate metric
    obj_ids = cfg.DATASETS.OBJ_IDS
    dataset_name = cfg.DATASETS.NAME
    meta_info = MetaInfo(dataset_name)
    models_3d = {obj_id: inout.load_ply(meta_info.model_tpath.format(obj_id=obj_id)) for obj_id in obj_ids}
    models_info = inout.load_json(meta_info.models_info_path, keys_to_int=True)
    diameters = {obj_id: models_info[obj_id]['diameter'] for obj_id in obj_ids}
    sym_obj_id = cfg.DATASETS.SYM_OBJS_ID
    if sym_obj_id == "bop":
        sym_obj_id = [k for k, v in models_info.items() if 'symmetries_discrete' in v or 'symmetries_continuous' in v]
    objs = load_objs(meta_info, obj_ids)
    renderer = ObjCoordRenderer(objs, [k for k in objs.keys()], cfg.DATASETS.RES_CROP)
    # set output_dir and resume
    cfg.OUTPUT_ROOT = os.path.abspath(args.eval_folder)

    for ck in args.ckpt:
        cfg.OUTPUT_DIR = os.path.join(cfg.OUTPUT_ROOT, os.path.splitext(ck)[0])
        if not os.path.exists(cfg.OUTPUT_DIR):
            os.mkdir(cfg.OUTPUT_DIR)
        cvs_path = cfg.OUTPUT_DIR
        cfg.VIS_DIR = os.path.join(cvs_path, "visualize")
        if not os.path.exists(cfg.VIS_DIR):
            os.mkdir(cfg.VIS_DIR)
        cfg.RESUME = os.path.join(cfg.OUTPUT_ROOT, ck)

        # TODO, temporary code to ensure code compatibility, should be deleted after
        # cfg.DATASETS.TEST_SCORE_THR / TRAIN_CROP / TEST_CROP had been set in config
        test_score_thr = cfg.DATASETS.get("TEST_SCORE_THR", 0.01)
        cfg.DATASETS.TEST_SCORE_THR = test_score_thr
        print(f"cfg.DATASETS.TEST_SCORE_THR is {cfg.DATASETS.TEST_SCORE_THR}, make sure it is the desired behavior")
        train_crop = cfg.DATASETS.get("TRAIN_CROP", [1.2, 1.5])
        cfg.DATASETS.TRAIN_CROP = train_crop
        print(f"cfg.DATASETS.TRAIN_CROP is {cfg.DATASETS.TRAIN_CROP}, make sure it is the desired behavior")
        test_crop = cfg.DATASETS.get("TEST_CROP", [1.3, 1.3])
        cfg.DATASETS.TEST_CROP = test_crop
        print(f"cfg.DATASETS.TEST_CROP is {cfg.DATASETS.TEST_CROP}, make sure it is the desired behavior")
        code_bit = cfg.MODEL.GEOMETRY_NET.get("CODE_BIT", 16)
        cfg.MODEL.GEOMETRY_NET.CODE_BIT = code_bit
        print(f"cfg.MODEL.GEOMETRY_NET.CODE_BIT is {cfg.MODEL.GEOMETRY_NET.CODE_BIT}, make sure it is the desired behavior")
        # build model
        assert cfg.MODEL.NAME == "SymNet"
        model = build_model(cfg)
        model.load_state_dict(torch.load(cfg.RESUME)['state_dict'])
        model.eval().to(device).freeze()

        # load data
        data_test = build_BOP_test_dataset(cfg, cfg.DATASETS.TEST, debug=cfg.DEBUG)
        loader_test = torch.utils.data.DataLoader(data_test,
                                                batch_size=1,
                                                num_workers=4,
                                                pin_memory=True,
                                                collate_fn=batch_data_test,
                                                )
        predictions = dict()
        time_forward = []
        for idx, batch in enumerate(tqdm(loader_test)):
            with add_timing_to_list(time_forward):
                out_dict = model.infer(
                    batch["rgb_crop"].to(device),
                    obj_idx=batch["obj_idx"].to(device),
                    K=batch["K_crop"].to(device),
                    AABB=batch["AABB_crop"].to(device),
                )
            out_rots = out_dict["rot"].detach().cpu().numpy()  # [b,3,3]
            out_transes = out_dict["trans"].detach().cpu().numpy()  # [b,3]

            for i in range(len(out_rots)):
                scene_id = batch['scene_id'][i]
                im_id = batch['img_id'][i]
                if scene_id != args.scene_id or im_id != args.image_id:
                    continue
                score = batch["det_score"][i] if "det_score" in batch.keys() else 1.0
                time = batch["det_time"][i] if "det_time" in batch.keys() else 1000.0

                obj_id = batch["obj_id"][i]
                gt_R = batch["cam_R_obj"][i]
                gt_t = batch["cam_t_obj"][i]

                if args.visualize:
                    debug_image_dir = os.path.abspath(
                        os.path.join(cfg.OUTPUT_ROOT, str(scene_id)+"_"+str(im_id)))

                    ### refine code
                    gt_entire_mask = preprogress_mask(batch["mask_crop"][0])
                    gt_mask = preprogress_mask(batch["mask_visib_crop"][0])

                    gt_code = (batch["code_crop"][0] * 255).astype(np.uint8)
                    gt_code = gt_code.transpose((1,2,0))
                    gt_code[gt_mask==0, :] = 0.8*255

                    pre_mask_prob = preprogress_mask(out_dict["visib_mask_prob"][0, 0])
                    pre_mask = np.zeros_like(pre_mask_prob, dtype=np.uint8)
                    pre_mask[pre_mask_prob > 127] = 255
                    pred_code_prob = (out_dict["binary_code_prob"][0].detach().cpu().numpy() * 255).astype(np.uint8)
                    pred_code_prob = pred_code_prob.transpose((1,2,0))
                    pred_code = np.zeros_like(pred_code_prob, dtype=np.uint8)
                    pred_code[pred_code_prob>127] = 255
                    pred_code[pre_mask==0, :] = 0.8 * 255
                    show_ims = []
                    show_titles = []
                    for i in range(16):
                        show_ims.append((pred_code[:, :, [i]]).repeat(3,2))
                        show_titles.append("bit " + str(i))
                    grid_show(show_ims, show_titles, row=4, col=4, save_path=os.path.join(debug_image_dir, "pred_code_images.jpg"))

                    show_ims = []
                    show_titles = []
                    for i in range(16):
                        show_ims.append(gt_code[:, :, [i]].repeat(3,2))
                        show_titles.append("bit " + str(i))
                    grid_show(show_ims, show_titles, row=4, col=4,
                                save_path=os.path.join(debug_image_dir, "groundTruth_code_images.jpg"))


                    pred_code_prob[pre_mask==0, :] = 0.8 * 255
                    show_ims = []
                    show_titles = []
                    for i in range(16):
                        show_ims.append(pred_code_prob[:, :, [i]].repeat(3,2))
                        show_titles.append("bit " + str(i))
                    grid_show(show_ims, show_titles, row=4, col=4,
                                save_path=os.path.join(debug_image_dir, "pred_code_before_thershold.jpg"))


if __name__ == "__main__":
    main()
