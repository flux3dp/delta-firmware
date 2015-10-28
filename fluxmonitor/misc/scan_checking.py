import cv2


class ScanChecking(object):
    """docstring for ScanChecking"""
    def __init__(self):
        super(ScanChecking, self).__init__()
        self.corner = (4, 4)

    def find_board(self, img):
        find, points = cv2.findChessboardCorners(img, self.corner, flags=cv2.CALIB_CB_FAST_CHECK)  # corner number
        if not find:
            return False
        else:
            criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 100, 0.001)
            cv2.cornerSubPix(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY), points, self.corner, (-1, -1), criteria)
            return True

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
        if self.find_board(img):
            return 'board finded'
        else:
            if not self.heuristic_guess(img):
                return 'guess didn\'t pull out'
            else:
                return 'guess open'
