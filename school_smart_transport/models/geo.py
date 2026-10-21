# -*- coding: utf-8 -*-
"""Pure helper functions (no Odoo): distances, corridors, ETA, scores. Easy to test."""
import math
import re

EARTH_RADIUS_M = 6371000.0

# points taken off a driver's behaviour score (100 = perfect trip)
SCORE_PENALTY = {'speeding': 5.0, 'harsh': 2.0, 'deviation': 5.0, 'left_on_board': 20.0}


def haversine_m(lat1, lon1, lat2, lon2):
    """Great-circle distance in metres."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = p2 - p1
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(a))


def _xy(lat0, lat, lon):
    """Local flat projection in metres around latitude lat0 (fine for a few kilometres)."""
    return (math.radians(lon) * EARTH_RADIUS_M * math.cos(math.radians(lat0)),
            math.radians(lat) * EARTH_RADIUS_M)


def point_to_segment_m(plat, plon, alat, alon, blat, blon):
    """Distance in metres from point P to the segment A-B."""
    px, py = _xy(plat, plat, plon)
    ax, ay = _xy(plat, alat, alon)
    bx, by = _xy(plat, blat, blon)
    dx, dy = bx - ax, by - ay
    length2 = dx * dx + dy * dy
    if length2 == 0:
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / length2))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def distance_to_polyline_m(plat, plon, points):
    """Distance from P to the path through `points` [(lat, lon), ...]. None when there is no path."""
    if not points:
        return None
    if len(points) == 1:
        return haversine_m(plat, plon, points[0][0], points[0][1])
    return min(point_to_segment_m(plat, plon, a[0], a[1], b[0], b[1]) for a, b in zip(points, points[1:]))


def offset_point(lat, lon, north_m=0.0, east_m=0.0):
    """The point `north_m` metres north and `east_m` metres east of (lat, lon)."""
    return (lat + math.degrees(north_m / EARTH_RADIUS_M),
            lon + math.degrees(east_m / (EARTH_RADIUS_M * math.cos(math.radians(lat)))))


def eta_minutes(distance_m, speed_kmh, road_factor=1.3, default_speed_kmh=25.0, min_speed_kmh=5.0):
    """Minutes to cover `distance_m` (straight line) on the road. A crawling / stopped vehicle uses the default speed."""
    speed = speed_kmh if speed_kmh and speed_kmh >= min_speed_kmh else default_speed_kmh
    return (distance_m * road_factor / 1000.0) / speed * 60.0


def parse_coordinates(text):
    """'11.0168, 76.9558' (also 'lat lon' or a pasted map link with both numbers) -> (lat, lon) or None."""
    numbers = re.findall(r'-?\d+(?:\.\d+)?', text or '')
    if len(numbers) < 2:
        return None
    lat, lon = float(numbers[0]), float(numbers[1])
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return None
    return lat, lon


def behaviour_score(speeding=0, harsh=0, deviations=0, left_on_board=0):
    """Driver behaviour of one trip: 100 minus penalties, never below 0."""
    penalty = (speeding * SCORE_PENALTY['speeding'] + harsh * SCORE_PENALTY['harsh']
               + deviations * SCORE_PENALTY['deviation'] + left_on_board * SCORE_PENALTY['left_on_board'])
    return max(0.0, 100.0 - penalty)
