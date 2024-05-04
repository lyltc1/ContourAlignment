import math
from pathlib import Path
import json
import os
import numpy as np

def RGB_to_class_id(RGB_image):
    # the input of this function has to be numpy array, due to the bit shift
    RGB_image = RGB_image.astype(int)
    class_id_R = RGB_image[:, :, 0]
    class_id_G = np.left_shift(RGB_image[:,:,1], 8)
    class_id_B = np.left_shift(RGB_image[:,:,2], 16)
    class_id_image = class_id_B + class_id_G + class_id_R
    return class_id_image

def class_id_to_class_code_images(class_id_image, class_base=2, iteration=16, number_of_class=65536):
    """
        class_id_image: 2D numpy array
    """
    if class_base ** iteration != number_of_class:
        raise ValueError('this combination of base and itration is not possible')
    iteration = int(iteration)
    class_id_image = class_id_image.astype(int)
    class_code_images = np.zeros((class_id_image.shape[0], class_id_image.shape[1], iteration))
    bit_step = math.log2(class_base)
    for i in range(iteration):
        shifted_value_1 = np.right_shift(class_id_image, int(bit_step * (iteration - i - 1)))
        shifted_value_2 = np.right_shift(class_id_image, int(bit_step * (iteration - i)))
        class_code_images[:, :, i] = shifted_value_1 - shifted_value_2 * (2 ** bit_step)
    return class_code_images

def class_code_to_class_id_and_class_id_max_images(class_code_img, bit=15, class_base=2):
    """ class code transform to class id
    : param class_code_img: (r,r,16) dtype=float64 min=0.0 max=1.0
    : param bit: which bit is considered right
    """
    class_id_img = np.zeros((class_code_img.shape[0], class_code_img.shape[1]), dtype=int)
    code_length = class_code_img.shape[2]
    for i in range(bit + 1):
        class_id_img += class_code_img[..., i] * (class_base**(code_length - 1 - i))
    class_id_max_img = class_id_img.copy() + 2 ** (code_length - 1 - bit) - 1
    return class_id_img, class_id_max_img


def load_decoders(decoder_dir, bit=16, obj_ids=None):
    decoders = {}
    if obj_ids is None:
        obj_ids = sorted(
            [int(p.name[-11:-5]) for p in decoder_dir.glob("Class_CorresPoint*.json")]
        )
    for obj_id in obj_ids:
        decoder_path = os.path.join(decoder_dir, f"Class_CorresPoint{obj_id:06d}.json")
        assert os.path.exists(decoder_path)
        with open(decoder_path, "r") as f:
            data = json.loads(f.read())
            corresponding = data["corresponding"]
            gathered_corresponding = dict()
            left = 0
            while left < 2**16:
                right = left + 2 ** (16 - bit)
                gathered_corresponding[left] = list()
                for i in range(left, right):
                    if corresponding[str(i)]:
                        gathered_corresponding[left].extend(corresponding[str(i)])
                left = right
            decoders[obj_id] = gathered_corresponding

    return decoders


def load_decoders_zebracode(decoder_dir: str, obj_ids):
    decoders = {}
    for obj_id in obj_ids:
        decoder_path = os.path.join(decoder_dir, 'models_GT_color', f'Class_CorresPoint{obj_id:06d}.txt')
        dict_class_id_3D_points = {}

        with open(decoder_path, "r") as f:
            first_line = f.readline()
            total_numer_class, divide_number_each_itration, number_of_itration = first_line.split(" ") 

            for line in f:
                line = line[:-1]
                code, x, y, z= line.split(" ")
                if "nan" in x:
                    dict_class_id_3D_points[int(code)] = []
                else:
                    dict_class_id_3D_points[int(code)] = [(float(x), float(y), float(z)),]
        decoders[obj_id] = dict_class_id_3D_points
    
    return decoders