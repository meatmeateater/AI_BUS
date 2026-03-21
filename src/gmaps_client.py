import logging
import os
from typing import Optional, List, Dict, Any
import googlemaps
from datetime import datetime

from config.settings import GOOGLE_MAPS_API_KEY

logger = logging.getLogger(__name__)
_DEBUG = os.getenv("DEBUG", "").lower() in ("1", "true", "yes")

# 初始化實例
gmaps = None
if GOOGLE_MAPS_API_KEY:
    try:
        gmaps = googlemaps.Client(key=GOOGLE_MAPS_API_KEY)
    except Exception as e:
        logger.error(f"Failed to initialize Google Maps client: {e}")

class GmapsClient:
    """
    處理 Google Maps Directions API 呼叫的客戶端
    """
    
    @classmethod
    def get_transit_route(cls, origin: str, destination: str) -> Optional[Dict[str, Any]]:
        """
        取得大眾運輸轉乘方案 (限公車/捷運)
        
        Args:
            origin: 起點站名或地址
            destination: 終點站名或地址
            
        Returns:
            若成功找到轉乘方案，回傳解析後的 dict，否則回傳 None
        """
        if not gmaps:
            logger.warning("GOOGLE_MAPS_API_KEY is not set.")
            return None
            
        try:
            now = datetime.now()
            # 呼叫 directions API，強制走大眾運輸
            # location 限制在大台北地區 (給定大致座標來 bias)
            directions_result = gmaps.directions(
                origin,
                destination,
                mode="transit",
                departure_time=now,
                language="zh-TW",
                region="tw"
            )
            
            if not directions_result:
                return None
                
            route = directions_result[0]
            leg = route['legs'][0]
            
            # 抽出時間與距離總和
            total_duration_text = leg.get('duration', {}).get('text', '')
            total_duration_value = leg.get('duration', {}).get('value', 0) // 60 # minutes
            
            steps_info = []
            
            # 解析每個 step
            for step in leg.get('steps', []):
                travel_mode = step.get('travel_mode')
                duration = step.get('duration', {}).get('text', '')
                
                if travel_mode == 'WALKING':
                    doc = step.get('html_instructions', '')
                    steps_info.append({
                        "type": "WALKING",
                        "instruction": doc,
                        "duration": duration
                    })
                elif travel_mode == 'TRANSIT':
                    transit_details = step.get('transit_details', {})
                    line = transit_details.get('line', {})
                    
                    vehicle_type = line.get('vehicle', {}).get('type', '')
                    short_name = line.get('short_name') or line.get('name', '')
                    
                    dep_stop = transit_details.get('departure_stop', {}).get('name', '')
                    arr_stop = transit_details.get('arrival_stop', {}).get('name', '')
                    
                    num_stops = transit_details.get('num_stops', 0)
                    
                    steps_info.append({
                        "type": "TRANSIT",
                        "vehicle": vehicle_type,
                        "route_name": short_name,
                        "departure_stop": dep_stop,
                        "arrival_stop": arr_stop,
                        "num_stops": num_stops,
                        "duration": duration
                    })
                    
            result = {
                "total_duration_text": total_duration_text,
                "total_duration_minutes": total_duration_value,
                "steps": steps_info,
            }
            # L-3: raw_legs 只在 DEBUG 模式保留，避免佔用不必要記憶體
            if _DEBUG:
                result["raw_legs"] = leg
            return result
            
        except Exception as e:
            logger.error(f"Google Maps API error: {e}", exc_info=True)
            return None

