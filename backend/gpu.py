"""The GPU desktop's one GPU, shared by the jobs that need it (#226).

Room reconstruction (#135) and a hazard's 4D step (#226) each fill most of the 8 GB, so they take
turns: each holds `GPU` while it runs, and the other waits. Visual positioning (#133) keeps its
small share and doesn't take part.
"""

import threading

GPU = threading.Lock()
