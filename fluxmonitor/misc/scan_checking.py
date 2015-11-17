
import cv2
import numpy as np


def compute_area(cords):
    # use determinant to compute area size
    cords = np.concatenate((cords, [cords[0]]), axis=0)
    tmp = [np.linalg.det(np.array([cords[i][:], cords[i + 1][:]])) for i in range(len(cords) - 1)]
    tmp = abs(sum(tmp)) / 2.
    return tmp


class ScanChecking(object):
    """docstring for ScanChecking"""

    corner = (4, 4)

    def __init__(self):
        super(ScanChecking, self).__init__()

    @classmethod
    def find_board(cls, img):
        find, points = cv2.findChessboardCorners(img, cls.corner, flags=cv2.CALIB_CB_FAST_CHECK | cv2.cv.CV_CALIB_CB_ADAPTIVE_THRESH)  # corner number
        if not find:
            return False, False
        else:
            criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 100, 0.001)
            cv2.cornerSubPix(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY), points, cls.corner, (-1, -1), criteria)
            return True, points

    @classmethod
    def chess_area(cls, img):
        find, points = cv2.findChessboardCorners(img, cls.corner, flags=cv2.CALIB_CB_FAST_CHECK | cv2.cv.CV_CALIB_CB_ADAPTIVE_THRESH)  # corner number
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
        if self.find_board(img)[0]:
            return 'chess board found'
        else:
            if not self.heuristic_guess(img):
                return 'guess didn\'t pull out'
            else:
                return 'guess open'


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
    get_matrix()
