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
    def find_board(cls, img):
        # corner number
        find, points = cv2.findChessboardCorners(img, cls.corner, flags=cv2.CALIB_CB_FAST_CHECK | cv2.cv.CV_CALIB_CB_ADAPTIVE_THRESH)

        if not find:
            return False, False
        else:
            criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER,
                        100, 0.001)
            cv2.cornerSubPix(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY), points,
                             cls.corner, (-1, -1), criteria)
            return True, points

    @classmethod
    def chess_area(cls, img, points):
        def compute_area(cords):
            # use determinant to compute area size
            cords = np.concatenate((cords, [cords[0]]), axis=0)
            tmp = [np.linalg.det(np.array([cords[i][:],
                                 cords[i + 1][:]])) for i in range(len(cords) - 1)]
            tmp = abs(sum(tmp)) / 2.
            return tmp
        criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 100, 0.001)
        cv2.cornerSubPix(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY), points, (5, 5), (-1, -1), criteria)

        rect = np.array([points[0][0], points[cls.corner[0] - 1][0], points[-1][0], points[-cls.corner[0]][0]])
        area = compute_area(rect)
        return area

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

    def check(self, img):
        # '00000001': open
        # '00000010': found chessboard
        result = 0
        if self.find_board(img)[0]:
            result |= (1 << 0)
            result |= (1 << 1)
        else:
            if not self.heuristic_guess(img):  # didn't pull out
                pass
            else:
                result |= (1 << 0)
        return str(result)

    def bias(p):
        '''
        input points of chess board
        return True(should go ccw) or False(should go cw)
        where should the plate turn
        '''
        if abs(p[0][0][0] - p[1][0][0]) > abs(p[0][0][1] - p[1][0][1]):
            # 0-1-2-3
            # 4-5-6-7
            # 8-9-10-11
            # 12-13-14-15
            l_index = [0, 12]
            r_index = [15, 3]
        else:
            # 12-8-4-0
            # 13-9-5-1
            # 14-10-6-2
            # 15-11-7-3
            l_index = [12, 0]
            r_index = [15, 3]
        # print(abs(p[l_index[0]][0][1] - p[l_index[1]][0][1]) - abs(p[r_index[0]][0][1] - p[r_index[1]][0][1]))
        return abs(p[l_index[0]][0][1] - p[l_index[1]][0][1]) < abs(p[r_index[0]][0][1] - p[r_index[1]][0][1])

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
        img_r = cv2.imread('../../../1113_b/{0:0>3}_R.jpg'.format(i))
        print i,

        if find_red(img_o, img_r, 'lumin'):
            p += 1
    print p



        # f,p = ScanChecking.find_board(img_o)
        # if f:
        #     print i,
        #     bias(p)
