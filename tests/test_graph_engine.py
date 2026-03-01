"""
tests/test_graph_engine.py — GraphEngine 單元測試
使用 mock 的圖資料來測試路徑搜尋邏輯，不需要真實 API 連線。
"""
import os
import sys
import json
import tempfile
import unittest

# Setup path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.graph_engine import GraphEngine


class TestGraphEngine(unittest.TestCase):
    """GraphEngine 路徑搜尋測試"""
    
    @classmethod
    def setUpClass(cls):
        """建立測試用的 mock 圖資料"""
        cls.mock_graph = {
            "stops": {
                "台北車站": {"routes": ["307", "299"]},
                "板橋站": {"routes": ["307", "藍線"]},
                "中山站": {"routes": ["299", "紅線"]},
                "西門站": {"routes": ["307", "紅線", "藍線"]},
                "三重站": {"routes": ["藍線", "橘線"]},
                "蘆洲站": {"routes": ["橘線"]},
            },
            "routes": {
                "307": ["台北車站", "西門站", "板橋站"],
                "299": ["台北車站", "中山站"],
                "紅線": ["中山站", "西門站"],
                "藍線": ["西門站", "板橋站", "三重站"],
                "橘線": ["三重站", "蘆洲站"],
            },
            "last_updated": "2026-01-01 00:00:00"
        }
        
        # 寫入暫存檔
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
        """測試圖載入"""
        self.assertTrue(self.engine.is_loaded)
        self.assertEqual(len(self.engine.stops), 6)
        self.assertEqual(len(self.engine.routes), 5)
    
    def test_find_best_stop_match_exact(self):
        """測試精確匹配站名"""
        result = self.engine.find_best_stop_match("台北車站")
        self.assertEqual(result, "台北車站")
    
    def test_find_best_stop_match_partial(self):
        """測試部分匹配站名"""
        result = self.engine.find_best_stop_match("板橋")
        self.assertEqual(result, "板橋站")
    
    def test_find_best_stop_match_not_found(self):
        """測試找不到站名"""
        result = self.engine.find_best_stop_match("不存在的站")
        self.assertIsNone(result)
    
    def test_get_route_stop_distance(self):
        """測試站距計算"""
        dist = self.engine.get_route_stop_distance("307", "台北車站", "板橋站")
        self.assertEqual(dist, 2)  # 台北車站 -> 西門站 -> 板橋站
    
    def test_get_route_stop_distance_not_found(self):
        """測試站不在路線上"""
        dist = self.engine.get_route_stop_distance("307", "台北車站", "蘆洲站")
        self.assertEqual(dist, 999)
    
    def test_find_candidate_paths_direct(self):
        """測試直達路線搜尋"""
        results = self.engine.find_candidate_paths("台北車站", "板橋站")
        self.assertTrue(len(results) > 0)
        self.assertEqual(results[0]["type"], "direct")
        self.assertEqual(results[0]["segments"][0]["route"], "307")
    
    def test_find_candidate_paths_transfer(self):
        """測試轉乘路線搜尋"""
        results = self.engine.find_candidate_paths("台北車站", "蘆洲站")
        self.assertTrue(len(results) > 0)
        # 台北車站 -> (307) -> 西門站 或 板橋站 -> (藍線) -> 三重站 -> (橘線) -> 蘆洲站
        # 應找到某種轉乘方案
        self.assertIn(results[0]["type"], ["transfer_greedy"])
    
    def test_find_candidate_paths_not_found(self):
        """測試找不到路線"""
        results = self.engine.find_candidate_paths("不存在", "也不存在")
        self.assertEqual(len(results), 0)
    
    def test_get_route_stops(self):
        """測試取得路線沿途站點"""
        stops = self.engine.get_route_stops("307", "台北車站", "板橋站")
        self.assertEqual(stops, ["台北車站", "西門站", "板橋站"])


class TestCacheManager(unittest.TestCase):
    """CacheManager 快取測試"""
    
    def test_get_or_fetch_miss_then_hit(self):
        """測試快取 miss 後 fetch，再次取得應為 hit"""
        from src.cache_manager import CacheManager
        
        # 清除可能的殘留快取
        test_key = "__test_route__"
        
        mock_data = {"GoDirStops": [{"Name": "Test", "ETA": 300}]}
        
        result = CacheManager.get_or_fetch(test_key, lambda x: mock_data)
        self.assertEqual(result, mock_data)
        
        # 第二次應從快取取得 (fetch_func 不會被呼叫)
        result2 = CacheManager.get_or_fetch(test_key, lambda x: None)
        self.assertEqual(result2, mock_data)
    
    def test_set_and_get(self):
        """測試直接 set/get"""
        from src.cache_manager import CacheManager
        
        CacheManager.set_route_data("__test2__", {"foo": "bar"})
        result = CacheManager.get_cached_route_data("__test2__")
        self.assertEqual(result, {"foo": "bar"})


if __name__ == "__main__":
    unittest.main()
