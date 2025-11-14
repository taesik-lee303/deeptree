#!/bin/bash
# 라즈베리파이에서 큰 파일/디렉토리 찾기

echo "=========================================="
echo "큰 파일/디렉토리 찾기"
echo "=========================================="
echo ""

# 홈 디렉토리에서 큰 파일 찾기 (상위 20개)
echo "=== 홈 디렉토리 큰 파일/디렉토리 (상위 20개) ==="
du -h ~ 2>/dev/null | sort -rh | head -20
echo ""

# 전체 시스템에서 큰 디렉토리 찾기 (상위 20개, sudo 필요)
echo "=== 전체 시스템 큰 디렉토리 (상위 20개) ==="
echo "주의: sudo 권한 필요"
sudo du -h / 2>/dev/null | sort -rh | head -20
echo ""

# 특정 크기 이상 파일 찾기 (100MB 이상)
echo "=== 100MB 이상 파일 찾기 ==="
find ~ -type f -size +100M -exec ls -lh {} \; 2>/dev/null | awk '{print $5, $9}'
echo ""

# 프로젝트 디렉토리 제외하고 큰 파일 찾기
echo "=== 프로젝트 디렉토리 제외 큰 파일 찾기 ==="
echo "현재 프로젝트 경로를 제외하고 검색합니다..."
PROJECT_PATH="${HOME}/deeptree"  # 프로젝트 경로 수정 필요
if [ -d "$PROJECT_PATH" ]; then
    find ~ -type f -size +50M ! -path "${PROJECT_PATH}/*" -exec ls -lh {} \; 2>/dev/null | awk '{print $5, $9}'
else
    echo "프로젝트 경로를 찾을 수 없습니다: $PROJECT_PATH"
fi
echo ""

echo "=========================================="
echo "검색 완료"
echo "=========================================="

