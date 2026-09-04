from math import asin, cos, radians, sin, sqrt


def haversine_distance_meters(
    lat1: float, lng1: float, lat2: float, lng2: float
) -> float:
    """Calculate the great circle distance in meters between two points on earth."""
    R = 6_371_000  # Earth radius in metres
    r_lat1, r_lng1, r_lat2, r_lng2 = map(
        radians, [float(lat1), float(lng1), float(lat2), float(lng2)]
    )
    dlat = r_lat2 - r_lat1
    dlng = r_lng2 - r_lng1
    a = sin(dlat / 2) ** 2 + cos(r_lat1) * cos(r_lat2) * sin(dlng / 2) ** 2
    return 2 * R * asin(sqrt(a))
