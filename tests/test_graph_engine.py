"""
tests/test_graph_engine.py — GraphEngine 單元測試 (v2, direction-aware)
使用 mock 的圖資料來測試路徑搜尋邏輯，不需要真實 API。
"""
import os
import sys
import json
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.graph_engine import GraphEngine, get_base_route_name, get_direction_label


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


class TestGraphEngine(unittest.TestCase):
    """GraphEngine 路徑搜尋測試 (direction-aware)"""
    
    @classmethod
    def setUpClass(cls):
        """建立 direction-aware 的 mock 圖資料"""
        cls.mock_graph = {
            "stops": {
                # 每個站列出所有經過的方向性路線（去程+返程）
                "台北車站": {"routes": ["307__go", "307__back", "299__go"]},
                "板橋站":   {"routes": ["307__go", "307__back", "藍線__go", "藍線__back"]},
                "中山站":   {"routes": ["299__go", "紅線__go"]},
                "西門站":   {"routes": ["307__go", "307__back", "紅線__go", "藍線__go", "藍線__back"]},
                "三重站":   {"routes": ["藍線__go", "藍線__back", "橘線__go"]},
                "蘆洲站":   {"routes": ["橘線__go"]},
            },
            "routes": {
                # Go directions
                "307__go":   ["台北車站", "西門站", "板橋站"],
                "307__back": ["板橋站", "西門站", "台北車站"],
                "299__go":   ["台北車站", "中山站"],
                "紅線__go":  ["中山站", "西門站"],
                "藍線__go":  ["西門站", "板橋站", "三重站"],
                "藍線__back": ["三重站", "板橋站", "西門站"],
                "橘線__go":  ["三重站", "蘆洲站"],
            },
            "last_updated": "2026-01-01 00:00:00",
            "version": 2,
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

    def test_load_graph(self):
        self.assertTrue(self.engine.is_loaded)
        self.assertEqual(len(self.engine.stops), 6)
        self.assertEqual(len(self.engine.routes), 7)
    
    def test_find_best_stop_match_exact(self):
        self.assertEqual(self.engine.find_best_stop_match("台北車站"), "台北車站")
    
    def test_find_best_stop_match_partial(self):
        self.assertEqual(self.engine.find_best_stop_match("板橋"), "板橋站")
    
    def test_find_best_stop_match_not_found(self):
        self.assertIsNone(self.engine.find_best_stop_match("不存在的站"))
    
    # === Direction-aware distance tests ===
    
    def test_distance_forward(self):
        """台北車站 -> 板橋站 via 307__go: 2 stops forward"""
        dist = self.engine.get_route_stop_distance("307__go", "台北車站", "板橋站")
        self.assertEqual(dist, 2)
    
    def test_distance_backward_rejected(self):
        """板橋站 -> 台北車站 via 307__go should be INVALID (wrong direction!)"""
        dist = self.engine.get_route_stop_distance("307__go", "板橋站", "台北車站")
        self.assertEqual(dist, 999)  # Rejected: would need 307__back
    
    def test_distance_correct_direction_back(self):
        """板橋站 -> 台北車站 via 307__back: 2 stops forward"""
        dist = self.engine.get_route_stop_distance("307__back", "板橋站", "台北車站")
        self.assertEqual(dist, 2)
    
    def test_distance_not_on_route(self):
        dist = self.engine.get_route_stop_distance("307__go", "台北車站", "蘆洲站")
        self.assertEqual(dist, 999)
    
    # === Path finding tests ===
    
    def test_find_direct_route(self):
        """台北車站 -> 板橋站 should find 307__go as direct"""
        results = self.engine.find_candidate_paths("台北車站", "板橋站")
        self.assertTrue(len(results) > 0)
        self.assertEqual(results[0]["type"], "direct")
        self.assertEqual(results[0]["segments"][0]["route"], "307__go")
    
    def test_no_wrong_direction_direct(self):
        """板橋站 -> 台北車站 should find 307__back, NOT 307__go"""
        results = self.engine.find_candidate_paths("板橋站", "台北車站")
        self.assertTrue(len(results) > 0)
        # Should be 307__back
        routes_found = [r["segments"][0]["route"] for r in results]
        self.assertIn("307__back", routes_found)
        self.assertNotIn("307__go", routes_found)
    
    def test_transfer_has_transfer_route(self):
        """Transfer candidates should include transfer_route field"""
        results = self.engine.find_candidate_paths("台北車站", "蘆洲站")
        self.assertTrue(len(results) > 0)
        for r in results:
            if r["type"] == "transfer_greedy":
                self.assertIn("transfer_route", r)
    
    def test_find_paths_not_found(self):
        results = self.engine.find_candidate_paths("不存在", "也不存在")
        self.assertEqual(len(results), 0)
    
    def test_get_route_stops_forward(self):
        stops = self.engine.get_route_stops("307__go", "台北車站", "板橋站")
        self.assertEqual(stops, ["台北車站", "西門站", "板橋站"])
    
    def test_get_route_stops_wrong_direction(self):
        """Wrong direction should return empty"""
        stops = self.engine.get_route_stops("307__go", "板橋站", "台北車站")
        self.assertEqual(stops, [])


class TestCacheManager(unittest.TestCase):
    """CacheManager 快取測試"""
    
    def test_get_or_fetch_miss_then_hit(self):
        from src.cache_manager import CacheManager
        
        test_key = "__test_route_v2__"
        mock_data = {"GoDirStops": [{"Name": "Test", "ETA": 300}]}
        
        result = CacheManager.get_or_fetch(test_key, lambda x: mock_data)
        self.assertEqual(result, mock_data)
        
        result2 = CacheManager.get_or_fetch(test_key, lambda x: None)
        self.assertEqual(result2, mock_data)
    
    def test_set_and_get(self):
        from src.cache_manager import CacheManager
        
        CacheManager.set_route_data("__test2_v2__", {"foo": "bar"})
        result = CacheManager.get_cached_route_data("__test2_v2__")
        self.assertEqual(result, {"foo": "bar"})


if __name__ == "__main__":
    unittest.main()
