# -*- coding: utf-8 -*-
import math

from odoo.tests.common import TransactionCase, tagged

from odoo.addons.school_smart_transport.models import geo


@tagged('post_install', '-at_install', 'school_smart_transport')
class TestGeo(TransactionCase):

    def test_haversine(self):
        self.assertEqual(geo.haversine_m(11.0, 77.0, 11.0, 77.0), 0.0)
        self.assertAlmostEqual(geo.haversine_m(11.0, 77.0, 11.001, 77.0), 111.2, delta=0.5)          # 0.001 degree of latitude
        self.assertAlmostEqual(geo.haversine_m(0.0, 0.0, 0.0, 1.0), 111195, delta=100)              # 1 degree on the equator
        self.assertAlmostEqual(geo.haversine_m(11.0, 77.0, 11.5, 77.5), geo.haversine_m(11.5, 77.5, 11.0, 77.0), places=6)

    def test_offset_point_round_trip(self):
        lat, lon = geo.offset_point(11.0, 77.0, north_m=400)
        self.assertAlmostEqual(geo.haversine_m(11.0, 77.0, lat, lon), 400, delta=0.5)
        lat, lon = geo.offset_point(11.0, 77.0, north_m=300, east_m=400)
        self.assertAlmostEqual(geo.haversine_m(11.0, 77.0, lat, lon), 500, delta=1)

    def test_distance_to_a_segment_and_a_path(self):
        a = (11.0, 77.0)
        b = geo.offset_point(*a, north_m=2000)
        beside = geo.offset_point(*geo.offset_point(*a, north_m=1000), east_m=300)
        self.assertAlmostEqual(geo.point_to_segment_m(beside[0], beside[1], a[0], a[1], b[0], b[1]), 300, delta=2)
        before = geo.offset_point(*a, north_m=-500)                                                  # beyond the end: distance to the end
        self.assertAlmostEqual(geo.point_to_segment_m(before[0], before[1], a[0], a[1], b[0], b[1]), 500, delta=2)
        self.assertAlmostEqual(geo.point_to_segment_m(a[0], a[1], a[0], a[1], a[0], a[1]), 0, delta=0.01)   # a zero length segment
        c = geo.offset_point(*b, east_m=2000)
        path = [a, b, c]
        near_second = geo.offset_point(*geo.offset_point(*b, east_m=1000), north_m=-250)
        self.assertAlmostEqual(geo.distance_to_polyline_m(near_second[0], near_second[1], path), 250, delta=2)
        self.assertIsNone(geo.distance_to_polyline_m(11.0, 77.0, []))
        self.assertAlmostEqual(geo.distance_to_polyline_m(*before, [a]), 500, delta=2)

    def test_eta(self):
        self.assertAlmostEqual(geo.eta_minutes(1000, 26, road_factor=1.3), 3.0, places=6)              # 1.3 km at 26 km/h
        self.assertAlmostEqual(geo.eta_minutes(1000, 0), 1.3 / 25 * 60, places=6)                      # stopped: the default speed
        self.assertAlmostEqual(geo.eta_minutes(1000, 3, default_speed_kmh=30), 1.3 / 30 * 60, places=6)  # crawling too
        self.assertGreater(geo.eta_minutes(2000, 30), geo.eta_minutes(1000, 30))
        self.assertEqual(geo.eta_minutes(0, 30), 0.0)

    def test_parse_coordinates(self):
        self.assertEqual(geo.parse_coordinates('11.0168, 76.9558'), (11.0168, 76.9558))
        self.assertEqual(geo.parse_coordinates('  11.0168   76.9558 '), (11.0168, 76.9558))
        self.assertEqual(geo.parse_coordinates('-33.86, 151.21'), (-33.86, 151.21))
        self.assertEqual(geo.parse_coordinates('https://maps.example/@11.0168,76.9558,17z')[0], 11.0168)
        for bad in ('', None, 'no numbers', '11.0', '95.0, 10.0', '10.0, 190.0'):
            self.assertIsNone(geo.parse_coordinates(bad), bad)

    def test_behaviour_score(self):
        self.assertEqual(geo.behaviour_score(), 100.0)
        self.assertEqual(geo.behaviour_score(speeding=2), 90.0)
        self.assertEqual(geo.behaviour_score(harsh=3), 94.0)
        self.assertEqual(geo.behaviour_score(deviations=1), 95.0)
        self.assertEqual(geo.behaviour_score(left_on_board=1), 80.0)
        self.assertEqual(geo.behaviour_score(speeding=100), 0.0)                                       # never below zero
        self.assertTrue(math.isfinite(geo.behaviour_score(speeding=1, harsh=1, deviations=1, left_on_board=1)))
