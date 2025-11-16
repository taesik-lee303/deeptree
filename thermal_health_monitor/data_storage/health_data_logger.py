"""
건강 데이터 저장 및 관리 모듈
"""

import logging
import json
import csv
import os
import numpy as np
from datetime import datetime
from pathlib import Path
from typing import List, Optional
from collections import deque

logger = logging.getLogger(__name__)


class HealthDataLogger:
    """
    건강 데이터를 저장하고 관리하는 클래스
    
    지원 형식:
    - JSON (구조화된 데이터)
    - CSV (스프레드시트 호환)
    """
    
    def __init__(
        self,
        data_dir: str = "health_data",
        max_memory_records: int = 1000
    ):
        """
        Args:
            data_dir: 데이터 저장 디렉토리
            max_memory_records: 메모리에 보관할 최대 레코드 수
        """
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        
        self.max_memory_records = max_memory_records
        self.memory_buffer = deque(maxlen=max_memory_records)
        
        # 세션 파일명 생성
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.session_file = self.data_dir / f"session_{timestamp}.json"
        self.csv_file = self.data_dir / f"session_{timestamp}.csv"
        
        # CSV 헤더 작성
        self._init_csv()
        
        logger.info(f"Data logger initialized. Session file: {self.session_file}")
    
    def _init_csv(self):
        """CSV 파일 초기화"""
        with open(self.csv_file, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow([
                'timestamp',
                'body_temperature',
                'heart_rate',
                'respiration_rate',
                'stress_index',
                'blood_flow_status',
                'fever_detected',
                'confidence'
            ])
    
    def log(self, health_metrics):
        """
        건강 지표 저장
        
        Args:
            health_metrics: HealthMetrics 객체
        """
        # 메모리 버퍼에 추가
        data_dict = health_metrics.to_dict()
        self.memory_buffer.append(data_dict)
        
        # JSON 파일에 추가 (append mode)
        self._append_json(data_dict)
        
        # CSV 파일에 추가
        self._append_csv(data_dict)
    
    def _append_json(self, data_dict: dict):
        """JSON 파일에 데이터 추가"""
        try:
            # 기존 데이터 읽기
            if self.session_file.exists():
                with open(self.session_file, 'r') as f:
                    data = json.load(f)
            else:
                data = {'records': []}
            
            # 새 레코드 추가
            data['records'].append(data_dict)
            
            # 저장
            with open(self.session_file, 'w') as f:
                json.dump(data, f, indent=2)
                
        except Exception as e:
            logger.error(f"Error writing JSON: {e}")
    
    def _append_csv(self, data_dict: dict):
        """CSV 파일에 데이터 추가"""
        try:
            with open(self.csv_file, 'a', newline='') as f:
                writer = csv.writer(f)
                writer.writerow([
                    data_dict.get('timestamp'),
                    data_dict.get('body_temperature'),
                    data_dict.get('heart_rate') or '',
                    data_dict.get('respiration_rate') or '',
                    data_dict.get('stress_index') or '',
                    data_dict.get('blood_flow_status') or '',
                    data_dict.get('fever_detected'),
                    data_dict.get('confidence')
                ])
        except Exception as e:
            logger.error(f"Error writing CSV: {e}")
    
    def get_recent_records(self, num_records: int = 100) -> List[dict]:
        """최근 레코드 조회"""
        return list(self.memory_buffer)[-num_records:]
    
    def get_statistics(self) -> dict:
        """통계 정보 계산"""
        if len(self.memory_buffer) == 0:
            return {}
        
        records = list(self.memory_buffer)
        
        # 체온 통계
        temps = [r['body_temperature'] for r in records if r.get('body_temperature')]
        # 심박수 통계
        hrs = [r['heart_rate'] for r in records if r.get('heart_rate')]
        # 호흡수 통계
        rrs = [r['respiration_rate'] for r in records if r.get('respiration_rate')]
        # 스트레스 지수 통계
        stresses = [r['stress_index'] for r in records if r.get('stress_index') is not None]
        
        stats = {
            'total_records': len(records),
            'temperature': {
                'mean': float(np.mean(temps)) if temps else None,
                'min': float(np.min(temps)) if temps else None,
                'max': float(np.max(temps)) if temps else None,
                'std': float(np.std(temps)) if temps else None
            },
            'heart_rate': {
                'mean': float(np.mean(hrs)) if hrs else None,
                'min': float(np.min(hrs)) if hrs else None,
                'max': float(np.max(hrs)) if hrs else None
            },
            'respiration_rate': {
                'mean': float(np.mean(rrs)) if rrs else None,
                'min': float(np.min(rrs)) if rrs else None,
                'max': float(np.max(rrs)) if rrs else None
            },
            'stress_index': {
                'mean': float(np.mean(stresses)) if stresses else None,
                'max': float(np.max(stresses)) if stresses else None
            }
        }
        
        return stats

