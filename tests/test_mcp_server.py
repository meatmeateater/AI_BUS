"""
tests/test_mcp_server.py — MCP Server 工具函數測試
Uses mock data to test plan_trip, calculate_best_route, and helpers.
Mock the 'mcp' package since it may not be installed in test environments.
"""
import os
import sys
import json
import unittest
from unittest.mock import patch, MagicMock
from datetime import datetime
from types import ModuleType

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

# Mock the 'mcp' package before importing mcp_server
# This allows tests to run without the mcp package installed
_mock_mcp = ModuleType('mcp')
_mock_server = ModuleType('mcp.server')
_mock_fastmcp = ModuleType('mcp.server.fastmcp')

class _MockFastMCP:
    def __init__(self, name): pass
    def tool(self): return lambda f: f
    def run(self): pass

_mock_fastmcp.FastMCP = _MockFastMCP
_mock_mcp.server = _mock_server
_mock_server.fastmcp = _mock_fastmcp

sys.modules.setdefault('mcp', _mock_mcp)
sys.modules.setdefault('mcp.server', _mock_server)
sys.modules.setdefault('mcp.server.fastmcp', _mock_fastmcp)

# Now safe to import
from src.mcp_server import (
    _normalize_stop_for_eta, find_canonical_route_name,
    calculate_best_route, plan_trip, check_transfer_safety,
    plan_trip_to_location, calculate_best_route_to_area,
    routes_map
)


class TestNormalizeStopForEta(unittest.TestCase):
    """Test _normalize_stop_for_eta matching logic."""
    
    def test_tai_trad_match(self):
        """台 should match 臺 in stop names."""
        stops = [
            {"Name": "臺北車站(忠孝)", "ETA": 300},
            {"Name": "西門站", "ETA": 200},
        ]
        matched = _normalize_stop_for_eta("台北車站", stops)
        self.assertEqual(len(matched), 1)
        self.assertEqual(matched[0]["Name"], "臺北車站(忠孝)")
    
    def test_mrt_prefix_match(self):
        """西門 should match 捷運西門站."""
        stops = [
            {"Name": "捷運西門站", "ETA": 100},
            {"Name": "東門站", "ETA": 200},
        ]
        matched = _normalize_stop_for_eta("西門", stops)
        self.assertEqual(len(matched), 1)
        self.assertEqual(matched[0]["Name"], "捷運西門站")
    
    def test_no_match(self):
        """Unrelated stop name returns empty."""
        stops = [{"Name": "板橋站", "ETA": 100}]
        matched = _normalize_stop_for_eta("松山", stops)
        self.assertEqual(len(matched), 0)
    
    def test_multiple_matches(self):
        """Multiple matching stops all returned."""
        stops = [
            {"Name": "臺北車站(忠孝)", "ETA": 300},
            {"Name": "臺北車站(承德)", "ETA": 400},
            {"Name": "西門站", "ETA": 200},
        ]
        matched = _normalize_stop_for_eta("台北", stops)
        self.assertEqual(len(matched), 2)


class TestFindCanonicalRouteName(unittest.TestCase):
    """Test route name lookup."""
    
    def test_exact_match(self):
        original = dict(routes_map)
        routes_map["307"] = "307"
        try:
            self.assertEqual(find_canonical_route_name("307"), "307")
        finally:
            routes_map.clear()
            routes_map.update(original)
    
    def test_no_match(self):
        original = dict(routes_map)
        routes_map.clear()
        routes_map["307"] = "307"
        try:
            result = find_canonical_route_name("完全不存在XXXXXXXXX")
            self.assertIsNone(result)
        finally:
            routes_map.clear()
            routes_map.update(original)


class TestCalculateBestRoute(unittest.TestCase):
    """Test calculate_best_route returns correct structure."""
    
    def test_no_candidates_returns_error(self):
        with patch('src.mcp_server.graph_engine') as mock_ge:
            mock_ge.find_candidate_paths.return_value = []
            result = calculate_best_route("不存在A", "不存在B")
            self.assertIn("error", result)
    
    def test_returns_results_key(self):
        """When candidates exist, result should have 'results' key."""
        mock_cand = [{
            "type": "direct",
            "segments": [{"route": "307__go", "from": "台北車站", "to": "西門站", "from_uid": "U1"}],
            "static_time": 5.0,
            "stop_count": 2
        }]
        
        with patch('src.mcp_server.graph_engine') as mock_ge, \
             patch('src.mcp_server.CacheManager') as mock_cm, \
             patch('src.mcp_server.find_canonical_route_name', return_value="307"):
            
            mock_ge.find_candidate_paths.return_value = mock_cand
            mock_cm.get_cached_route_data.return_value = {
                "GoDirStops": [{"Name": "台北車站", "StopUID": "U1", "ETA": 180}]
            }
            
            result = calculate_best_route("台北車站", "西門")
            self.assertIn("results", result)
            self.assertTrue(len(result["results"]) > 0)
            self.assertEqual(result["results"][0]["type"], "direct")


class TestPlanTrip(unittest.TestCase):
    """Test plan_trip output format."""
    
    def test_error_case(self):
        with patch('src.mcp_server.calculate_best_route', return_value={"error": "No candidates"}):
            result = plan_trip("不存在A", "不存在B")
            self.assertIn("找不到", result)
    
    def test_direct_format(self):
        """Direct route output should contain key markers."""
        mock_result = {
            "results": [{
                "type": "direct",
                "segments": [{"route": "307__go", "from": "台北車站", "to": "西門站"}],
                "total_time": 8,
                "wait_text": "3 分鐘",
                "stop_count": 2,
                "safety_note": "",
                "display_route": "307",
                "static_time": 5.0,
            }]
        }
        
        with patch('src.mcp_server.calculate_best_route', return_value=mock_result):
            result = plan_trip("台北車站", "西門")
            self.assertIn("方案 1", result)
            self.assertIn("307", result)
            self.assertIn("直達", result)
    
    def test_transfer_format(self):
        """Transfer route output should prompt re-query."""
        mock_result = {
            "results": [{
                "type": "transfer_greedy",
                "segments": [{"route": "299__go", "from": "台北車站", "to": "中山站"}],
                "transfer_stop": "中山站",
                "transfer_route": "紅線__go",
                "total_time": 25,
                "wait_text": "5 分鐘",
                "stop_count": 3,
                "safety_note": "(班次密集)",
                "display_route": "299",
                "static_time": 7.5,
            }]
        }
        
        with patch('src.mcp_server.calculate_best_route', return_value=mock_result):
            result = plan_trip("台北車站", "西門")
            self.assertIn("轉乘", result)
            self.assertIn("中山站", result)
            self.assertIn("再問我", result)
    
    def test_exception_handling(self):
        """plan_trip should catch exceptions gracefully."""
        with patch('src.mcp_server.calculate_best_route', side_effect=RuntimeError("boom")):
            result = plan_trip("A", "B")
            self.assertIn("錯誤", result)


class TestCheckTransferSafety(unittest.TestCase):
    """Test check_transfer_safety edge cases."""
    
    def test_no_client(self):
        with patch('src.mcp_server.BusCrawler') as mock_bc:
            mock_bc.get_client.return_value = None
            is_safe, reason, wait = check_transfer_safety("307", datetime.now())
            self.assertTrue(is_safe)
            self.assertIn("無法驗證", reason)


class TestPlanTripToLocation(unittest.TestCase):
    """測試 plan_trip_to_location GPS 半徑搜尋。"""

    def test_error_no_nearby(self):
        """附近沒站牌時回傳錯誤。"""
        with patch('src.mcp_server.graph_engine') as mock_ge:
            mock_ge.find_nearby_stops.return_value = []
            result = plan_trip_to_location("大安森林公園", "海上", 25.0, 122.5)
            self.assertIn("找不到", result)

    def test_output_contains_walking(self):
        """輸出應包含步行距離和目的地名稱。"""
        mock_result = {
            "results": [{
                "type": "direct",
                "segments": [{"route": "680__go", "from": "大安森林公園", "to": "信義光復路口"}],
                "total_time": 12,
                "wait_text": "3 分鐘",
                "stop_count": 4,
                "safety_note": "",
                "display_route": "680",
                "static_time": 10.0,
                "walk_min": 2.0,
                "walk_distance_m": 150,
                "dest_stop": "信義光復路口",
            }],
            "nearby_count": 5
        }
        with patch('src.mcp_server.calculate_best_route_to_area', return_value=mock_result):
            result = plan_trip_to_location("大安森林公園", "台北101", 25.0339, 121.5645)
            self.assertIn("台北101", result)
            self.assertIn("步行", result)
            self.assertIn("150m", result)
            self.assertIn("方案 1", result)

    def test_exception_handling(self):
        """應 catch exceptions。"""
        with patch('src.mcp_server.calculate_best_route_to_area', side_effect=RuntimeError("boom")):
            result = plan_trip_to_location("A", "B", 25.0, 121.0)
            self.assertIn("錯誤", result)


if __name__ == "__main__":
    unittest.main()
