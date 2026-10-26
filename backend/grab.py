"""Keep a grabbed object where it was relative to the controller, so a grab does not teleport it."""

import math

Vector = tuple[float, float, float]
Quaternion = tuple[float, float, float, float]


def rotate(orientation: Quaternion, vector: Vector) -> Vector:
    """Rotate `vector` by a unit quaternion (x, y, z, w)."""

    qx, qy, qz, qw = orientation
    x, y, z = vector
    cx = qy * z - qz * y
    cy = qz * x - qx * z
    cz = qx * y - qy * x
    dx = qy * cz - qz * cy
    dy = qz * cx - qx * cz
    dz = qx * cy - qy * cx
    return (
        x + 2 * qw * cx + 2 * dx,
        y + 2 * qw * cy + 2 * dy,
        z + 2 * qw * cz + 2 * dz,
    )


def normalize(orientation: Quaternion) -> Quaternion | None:
    qx, qy, qz, qw = orientation
    length = math.sqrt(qx * qx + qy * qy + qz * qz + qw * qw)
    if length < 1e-6:
        return None
    return (qx / length, qy / length, qz / length, qw / length)


def grab_offset(grip: Vector, orientation: Quaternion, box: Vector) -> Vector:
    """Where the box sits in the grip's local frame, so the grip can move without a jump."""

    qx, qy, qz, qw = orientation
    return rotate((-qx, -qy, -qz, qw), (box[0] - grip[0], box[1] - grip[1], box[2] - grip[2]))


def grabbed_point(grip: Vector, orientation: Quaternion, offset: Vector) -> Vector:
    """The box position for a grip pose and the offset taken when it was grabbed."""

    moved = rotate(orientation, offset)
    return (grip[0] + moved[0], grip[1] + moved[1], grip[2] + moved[2])
