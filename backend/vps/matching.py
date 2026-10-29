"""Matching a frame's keypoints to a map frame's, by their SuperPoint descriptors (#133).

Mutual nearest neighbours with Lowe's ratio test: a pair is kept when each keypoint is the other's
closest, and that closest is clearly closer than the next. It needs nothing beyond numpy. LightGlue
is usually more robust on hard views, and can replace it behind the same `match` once installed.
"""

import numpy as np

from backend.vps.localize import Features

# A pair is kept when its best distance is below this share of the second best.
RATIO = 0.9


class MutualNearest:
    model = f"mutual nearest neighbours, ratio {RATIO}"

    def match(self, query: Features, map_frame: Features) -> np.ndarray:
        mine, theirs = query[1], map_frame[1]
        if len(mine) < 2 or len(theirs) < 2:
            return np.zeros((0, 2), dtype=int)
        # SuperPoint descriptors are unit length, so squared distance is 2 - 2 x similarity.
        distance = np.sqrt(np.maximum(2 - 2 * (mine @ theirs.T), 0))
        nearest = np.argsort(distance, axis=1)[:, :2]
        rows = np.arange(len(mine))
        best, second = distance[rows, nearest[:, 0]], distance[rows, nearest[:, 1]]
        back = np.argmin(distance, axis=0)
        kept = (back[nearest[:, 0]] == rows) & (best < RATIO * second)
        return np.column_stack([rows[kept], nearest[kept, 0]])
