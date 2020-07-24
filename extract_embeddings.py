import logging
import os
import sys
sys.path.append('/root/fr/')
import torch
import torch.nn as nn
import torch.optim as optim
import torch.nn.functional as F
from torch.autograd import Variable

torch.backends.cudnn.bencmark = True

import os, sys, cv2, random, datetime
import argparse
import numpy as np
import zipfile
from timeit import default_timer as timer
from PIL import Image
from itertools import cycle
from glob import glob

from sphereface.dataset import ImageDataset
from cp2tform import get_similarity_transform_for_cv2
import sphereface.net_sphere as net_sphere

# USAGE
# python extract_embeddings.py --dataset dataset --embeddings output/embeddings.pickle \
#	--detector face_detection_model --embedding-model openface_nn4.small2.v1.t7

# import the necessary packages
from imutils import paths
import numpy as np
import argparse
import imutils
import pickle
import cv2
import os

# construct the argument parser and parse the arguments
ap = argparse.ArgumentParser()
ap.add_argument("-i", "--dataset", default="dataset",
    help="path to input directory of faces + images")
ap.add_argument("-e", "--embeddings", default="embeddings.pickle",
    help="path to output serialized db of facial embeddings")
ap.add_argument("-d", "--detector", default="face_detection_model",
    help="path to OpenCV's deep learning face detector")
ap.add_argument("-m", "--embedding-model", default="openface_nn4.small2.v1.t7",
    help="path to OpenCV's deep learning face embedding model")
ap.add_argument("-c", "--confidence", type=float, default=0.5,
    help="minimum probability to filter weak detections")
ap.add_argument(
    "--sphere_model", "-sm", default="sphereface/model/sphere20a_20171020.pth", type=str
)
args = vars(ap.parse_args())

# load our serialized face detector from disk
print("[INFO] loading face detector...")
protoPath = os.path.sep.join([args["detector"], "deploy.prototxt"])
modelPath = os.path.sep.join([args["detector"],
    "res10_300x300_ssd_iter_140000.caffemodel"])
detector = cv2.dnn.readNetFromCaffe(protoPath, modelPath)

# load our serialized face embedding model from disk
print("[INFO] loading face recognizer...")
embedder = cv2.dnn.readNetFromTorch(args["embedding_model"])

# grab the paths to the input images in our dataset
print("[INFO] quantifying faces...")
imagePaths = list(paths.list_images(args["dataset"]))

# initialize our lists of extracted facial embeddings and
# corresponding people names
knownEmbeddings = []
knownNames = []

# initialize the total number of faces processed
total = 0


net = getattr(net_sphere, "sphere20a")()
net.load_state_dict(torch.load(args["sphere_model"]))
net.cuda()
net.eval()
net.feature = True
def predict(face):
    img = cv2.resize(face, (112, 96))
    imglist = [img, cv2.flip(img, 1), img, cv2.flip(img, 1)]
    for i in range(len(imglist)):
        imglist[i] = imglist[i].transpose(2, 0, 1).reshape((1, 3, 112, 96))
        imglist[i] = (imglist[i] - 127.5) / 128.0

    img = np.vstack(imglist)
    img = Variable(torch.from_numpy(img).float(), volatile=True).cuda()
    output = net(img)
    f = output.data
    f1, f2 = f[0], f[2]
    cosdistance = f1.dot(f2) / (f1.norm() * f2.norm() + 1e-5)
    distance = 1-cosdistance
    return f1

# loop over the image paths
for (i, imagePath) in enumerate(imagePaths):
    # extract the person name from the image path
    print("[INFO] processing image {}/{}".format(i + 1,
        len(imagePaths)))
    name = imagePath.split(os.path.sep)[-2]

    # load the image, resize it to have a width of 600 pixels (while
    # maintaining the aspect ratio), and then grab the image
    # dimensions
    image = cv2.imread(imagePath)
    image = imutils.resize(image, width=600)
    (h, w) = image.shape[:2]

    # construct a blob from the image
    imageBlob = cv2.dnn.blobFromImage(
        cv2.resize(image, (300, 300)), 1.0, (300, 300),
        (104.0, 177.0, 123.0), swapRB=False, crop=False)

    # apply OpenCV's deep learning-based face detector to localize
    # faces in the input image
    detector.setInput(imageBlob)
    detections = detector.forward()

    # ensure at least one face was found
    if len(detections) > 0:
        # we're making the assumption that each image has only ONE
        # face, so find the bounding box with the largest probability
        i = np.argmax(detections[0, 0, :, 2])
        confidence = detections[0, 0, i, 2]

        # ensure that the detection with the largest probability also
        # means our minimum probability test (thus helping filter out
        # weak detections)
        if confidence > args["confidence"]:
            # compute the (x, y)-coordinates of the bounding box for
            # the face
            box = detections[0, 0, i, 3:7] * np.array([w, h, w, h])
            (startX, startY, endX, endY) = box.astype("int")

            # extract the face ROI and grab the ROI dimensions
            face = image[startY:endY, startX:endX]
            (fH, fW) = face.shape[:2]

            # ensure the face width and height are sufficiently large
            if fW < 20 or fH < 20:
                continue

            # construct a blob for the face ROI, then pass the blob
            # through our face embedding model to obtain the 128-d
            # quantification of the face
            # faceBlob = cv2.dnn.blobFromImage(face, 1.0 / 255,
            # 	(96, 96), (0, 0, 0), swapRB=True, crop=False)
            # embedder.setInput(faceBlob)
            # vec = embedder.forward()
            vec = predict(face).cpu()

            # add the name of the person + corresponding face
            # embedding to their respective lists
            knownNames.append(name)
            knownEmbeddings.append(vec.flatten())
            total += 1

# dump the facial embeddings + names to disk
print("[INFO] serializing {} encodings...".format(total))
data = {"embeddings": knownEmbeddings, "names": knownNames}
f = open(args["embeddings"], "wb")
f.write(pickle.dumps(data))
f.close()