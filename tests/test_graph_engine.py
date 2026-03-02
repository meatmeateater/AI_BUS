"""
tests/test_graph_engine.py — GraphEngine 單元測試 (v3, with UID + index + GPS)
"""
import os
import sys
import json
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.graph_engine import (
    GraphEngine, get_base_route_name, get_direction_label, haversine_distance
)


class TestHelpers(unittest.TestCase):
    """Test helper functions."""
    
    def test_get_base_route_name_go(self):
        self.assertEqual(get_base_route_name("307__go"), "307")
    
    def test_get_base_route_name_back(self):
        self.assertEqual(get_base_route_name("復興幹線__back"), "復興幹線")
    
    def test_get_base_route_name_no_suffix(self):
        self.assertEqual(get_base_route_name("307"), "307")
    
    def test_get_direction_label(self):
        self.assertEqual(get_direction_label("307__go"), "去程")
        self.assertEqual(get_direction_label("307__back"), "返程")
        self.assertEqual(get_direction_label("307"), "")
    
    def test_haversine_same_point(self):
        d = haversine_distance(25.0, 121.5, 25.0, 121.5)
        self.assertAlmostEqual(d, 0, places=0)
    
    def test_haversine_known_distance(self):
        # 台北車站 ~ 板橋站 roughly 7-8 km
        d = haversine_distance(25.0478, 121.5170, 25.0145, 121.4627)
        self.assertTrue(5000 < d < 10000)


class TestGraphEngine(unittest.TestCase):
    """GraphEngine v3 tests"""
    
    @classmethod
    def setUpClass(cls):
        cls.mock_graph = {
            "stops": {
                "台北車站":   {"routes": ["307__go", "307__back", "299__go"],
                             "lat": 25.0478, "lon": 121.517},
                "板橋站":     {"routes": ["307__go", "307__back", "藍線__go", "藍線__back"],
                             "lat": 25.0145, "lon": 121.4627},
                "中山站":     {"routes": ["299__go", "紅線__go"],
                             "lat": 25.0529, "lon": 121.5206},
                "西門站":     {"routes": ["307__go", "307__back", "紅線__go", "藍線__go", "藍線__back"],
                             "lat": 25.0421, "lon": 121.508},
                "三重站":     {"routes": ["藍線__go", "藍線__back", "橘線__go"],
                             "lat": 25.0617, "lon": 121.4729},
                "蘆洲站":     {"routes": ["橘線__go"],
                             "lat": 25.0848, "lon": 121.4643},
            },
            "routes": {
                "307__go":    ["台北車站", "西門站", "板橋站"],
                "307__back":  ["板橋站", "西門站", "台北車站"],
                "299__go":    ["台北車站", "中山站"],
                "紅線__go":   ["中山站", "西門站"],
                "藍線__go":   ["西門站", "板橋站", "三重站"],
                "藍線__back": ["三重站", "板橋站", "西門站"],
                "橘線__go":   ["三重站", "蘆洲站"],
            },
            "stop_uid_map": {
                "307__go": {"台北車站": "TPE001", "西門站": "TPE002", "板橋站": "TPE003"},
                "307__back": {"板橋站": "TPE003", "西門站": "TPE002", "台北車站": "TPE001"},
            },
            "version": 3,
            "direction_aware": True
        }
        
        cls.temp_file = tempfile.NamedTemporaryFile(
            mode='w', suffix='.json', delete=False, encoding='utf-8'
        )
        json.dump(cls.mock_graph, cls.temp_file, ensure_ascii=False)
        cls.temp_file.close()
        cls.engine = GraphEngine(cls.temp_file.name)
    
    @classmethod
    def tearDownClass(cls):
        os.unlink(cls.temp_file.name)

    # === Load & Basic ===
    
    def test_load_graph(self):
        self.assertTrue(self.engine.is_loaded)
        self.assertEqual(len(self.engine.stops), 6)
        self.assertEqual(len(self.engine.routes), 7)

    def test_stop_index_built(self):
        """P2: Pre-computed index should be built on load."""
        self.assertIn("307__go", self.engine._stop_index)
        self.assertIn("台北車站", self.engine._stop_index["307__go"])
        self.assertEqual(self.engine._stop_index["307__go"]["台北車站"], [0])
    
    # === Stop Matching ===
    
    def test_exact_match(self):
        self.assertEqual(self.engine.find_best_stop_match("台北車站"), "台北車站")
    
    def test_partial_match(self):
        self.assertEqual(self.engine.find_best_stop_match("板橋"), "板橋站")
    
    def test_not_found(self):
        self.assertIsNone(self.engine.find_best_stop_match("不存在的站"))
    
    def test_gps_match(self):
        """P2: GPS-based disambiguation."""
        # 在西門站附近搜「站」— 應優先返回最近的
        result = self.engine.find_best_stop_match("站", ref_lat=25.042, ref_lon=121.508)
        self.assertEqual(result, "西門站")
    
    # === UID ===
    
    def test_get_stop_uid(self):
        """P1: StopUID lookup."""
        uid = self.engine.get_stop_uid("307__go", "台北車站")
        self.assertEqual(uid, "TPE001")
    
    def test_get_stop_uid_missing(self):
        uid = self.engine.get_stop_uid("299__go", "台北車站")
        self.assertIsNone(uid)
    
    # === GPS ===
    
    def test_get_stop_gps(self):
        """P2: GPS coordinate lookup."""
        gps = self.engine.get_stop_gps("台北車站")
        self.assertIsNotNone(gps)
        self.assertAlmostEqual(gps[0], 25.0478, places=3)
    
    # === Direction-aware distance (using pre-computed index) ===
    
    def test_distance_forward(self):
        self.assertEqual(self.engine.get_route_stop_distance("307__go", "台北車站", "板橋站"), 2)
    
    def test_distance_backward_rejected(self):
        self.assertEqual(self.engine.get_route_stop_distance("307__go", "板橋站", "台北車站"), 999)
    
    def test_distance_correct_direction_back(self):
        self.assertEqual(self.engine.get_route_stop_distance("307__back", "板橋站", "台北車站"), 2)
    
    def test_distance_not_on_route(self):
        self.assertEqual(self.engine.get_route_stop_distance("307__go", "台北車站", "蘆洲站"), 999)
    
    # === Path finding ===
    
    def test_find_direct_route(self):
        results = self.engine.find_candidate_paths("台北車站", "板橋站")
        self.assertTrue(len(results) > 0)
        self.assertEqual(results[0]["type"], "direct")
        self.assertEqual(results[0]["segments"][0]["route"], "307__go")
    
    def test_direct_has_uid(self):
        """P1: Direct candidate should include from_uid."""
        results = self.engine.find_candidate_paths("台北車站", "板橋站")
        self.assertEqual(results[0]["segments"][0].get("from_uid"), "TPE001")
    
    def test_no_wrong_direction_direct(self):
        results = self.engine.find_candidate_paths("板橋站", "台北車站")
        routes_found = [r["segments"][0]["route"] for r in results]
        self.assertIn("307__back", routes_found)
        self.assertNotIn("307__go", routes_found)
    
    def test_transfer_has_transfer_route(self):
        results = self.engine.find_candidate_paths("台北車站", "蘆洲站")
        self.assertTrue(len(results) > 0)
        for r in results:
            if r["type"] == "transfer_greedy":
                self.assertIn("transfer_route", r)
    
    def test_paths_not_found(self):
        self.assertEqual(self.engine.find_candidate_paths("不存在", "也不存在"), [])
    
    def test_get_route_stops_forward(self):
        self.assertEqual(
            self.engine.get_route_stops("307__go", "台北車站", "板橋站"),
            ["台北車站", "西門站", "板橋站"]
        )
    
    def test_get_route_stops_wrong_direction(self):
        self.assertEqual(self.engine.get_route_stops("307__go", "板橋站", "台北車站"), [])


class TestCacheManager(unittest.TestCase):
    def test_get_or_fetch_miss_then_hit(self):
        from src.cache_manager import CacheManager
        test_key = "__test_v3__"
        mock = {"GoDirStops": [{"Name": "Test", "ETA": 300}]}
        r1 = CacheManager.get_or_fetch(test_key, lambda x: mock)
        self.assertEqual(r1, mock)
        r2 = CacheManager.get_or_fetch(test_key, lambda x: None)
        self.assertEqual(r2, mock)
    
    def test_set_and_get(self):
        from src.cache_manager import CacheManager
        CacheManager.set_route_data("__test2_v3__", {"foo": "bar"})
        self.assertEqual(CacheManager.get_cached_route_data("__test2_v3__"), {"foo": "bar"})


if __name__ == "__main__":
    unittest.main()
