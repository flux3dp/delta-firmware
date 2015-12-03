import os
from collections import Counter
import sys

import cv2
import numpy as np


class ScanChecking(object):
    """docstring for ScanChecking"""

    corner = (4, 4)

    def __init__(self):
        super(ScanChecking, self).__init__()

    @classmethod
    def find_board(cls, img, fast=True):
        # corner number
        if fast:
            flag = cv2.CALIB_CB_FAST_CHECK | cv2.cv.CV_CALIB_CB_ADAPTIVE_THRESH
        else:
            flag = cv2.cv.CV_CALIB_CB_ADAPTIVE_THRESH
        find, points = cv2.findChessboardCorners(img, cls.corner, flags=flag)
        if not find:
            return False, False
        else:
            if not fast:
                criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 100, 0.001)
                cv2.cornerSubPix(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY), points, cls.corner, (-1, -1), criteria)
            if abs(points[0][0][0] - points[1][0][0]) > abs(points[0][0][1] - points[1][0][1]):
                # 0-1-2-3
                # 4-5-6-7
                # 8-9-10-11
                # 12-13-14-15
                new_index = range(16)
                pass
            else:
                # 12-8-4-0
                # 13-9-5-1
                # 14-10-6-2
                # 15-11-7-3
                new_index = [12, 8, 4, 0, 13, 9, 5, 1, 14, 10, 6, 2, 15, 11, 7, 3]
            points = points[new_index, :, :]
            return True, points

    @classmethod
    def chess_area(cls, points):
        def compute_area(cords):
            # use determinant to compute area size
            cords = np.concatenate((cords, [cords[0]]), axis=0)
            tmp = [np.linalg.det(np.array([cords[i][:], cords[i + 1][:]])) for i in range(len(cords) - 1)]
            tmp = abs(sum(tmp)) / 2.
            return tmp

        rect = np.array([points[0][0], points[cls.corner[0] - 1][0], points[-1][0], points[-cls.corner[0]][0]])
        area = compute_area(rect)
        return area

    @classmethod
    def inhence(cls, points):
        criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 100, 0.001)
        cv2.cornerSubPix(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY), points, cls.corner, (-1, -1), criteria)
        return points

    def heuristic_guess(self, img):
        ok_score = 0
        if sum(cv2.meanStdDev(img)[1]) > 70:  # TODO: record magic number?
            ok_score += 1
        else:
            ok_score -= 1

        if ok_score >= 0:
            return True
        else:
            return False

    @classmethod
    def check(cls, img):
        # '00000001': open
        # '00000010': found chessboard
        result = 0
        if cls.find_board(img)[0]:
            result |= (1 << 0)
            result |= (1 << 1)
        else:
            if not cls.heuristic_guess(img):  # didn't pull out
                pass
            else:
                result |= (1 << 0)
        return str(result)

    @classmethod
    def get_bias(cls, p):
        '''
        input points of chess board
        return True(should go ccw) or False(should go cw)
        where should the plate turn
        '''
        # 0-1-2-3
        # 4-5-6-7
        # 8-9-10-11
        # 12-13-14-15
        return abs(p[0][0][1] - p[12][0][1]) - abs(p[3][0][1] - p[15][0][1])

    def find_red(img1, img2, mode='red'):
        '''
        return the indices of maximum of each row in diff(img1, img2)
        can shoose maximun of red or lumin
        (rot: red is better)
        '''
        thres = 50
        d = cv2.absdiff(img1, img2)

        if mode == 'red':
            indices = np.argmax(d[:, :, 2], axis=1)

        elif mode == 'lumin':
            indices = []
            d = d[:, :, 0] * 0.7152 + d[:, :, 1] * 0.0722 + d[:, :, 2] * 0.2126
            indices = np.argmax(d, axis=1)

        cnt = Counter()
        for i in indices:
            cnt[i] += 1
        p = []
        for i in cnt.most_common():
            if i[1] >= 50:
                p.append(i[0])
            else:
                break
        if p:
            return round(sum(p) / len(p))
        else:
            return False


def get_matrix():
    img = cv2.imread('../../../1113_b/038_O.jpg')
    f, p = ScanChecking.find_board(img)
    if f:
        cv2.drawChessboardCorners(img, (4, 4), p, f)
        print([i[0][0] for i in p])
        print(sum(i[0][0] for i in p) / 16)
        # cv2.imshow('image', img)
        # cv2.waitKey(0)
        # cv2.destroyAllWindows()


if __name__ == '__main__':
    # get_matrix()
    p = 0
    for i in range(0, 400):
        img_o = cv2.imread('../../../1113_b/{0:0>3}_O.jpg'.format(i))
    #     img_r = cv2.imread('../../../1113_b/{0:0>3}_R.jpg'.format(i))
    #     print i,

    #     if find_red(img_o, img_r, 'lumin'):
    #         p += 1
    # print p
        f, p = ScanChecking.find_board(img_o, fast=False)
        if f:
            print i,
            ScanChecking.get_bias(p)
