#!/bin/bash
# localepurge 자동 설치 및 설정 스크립트
# 한국어(ko_KR)와 영어(en_US) 로케일만 유지

set -e

echo "=========================================="
echo "localepurge 자동 설치 및 설정"
echo "=========================================="
echo ""

# debconf 설정 (대화형 프롬프트 없이 자동 설정)
echo "=== debconf 설정 ==="
echo 'localepurge localepurge/use-not-installed boolean true' | sudo debconf-set-selections
echo 'localepurge localepurge/verbose boolean false' | sudo debconf-set-selections
echo 'localepurge localepurge/showfreedspace boolean true' | sudo debconf-set-selections
echo 'localepurge localepurge/nopurge multiselect en, en_US, en_US.UTF-8, ko, ko_KR, ko_KR.UTF-8' | sudo debconf-set-selections
echo 'localepurge localepurge/none_selected boolean false' | sudo debconf-set-selections
echo "완료"
echo ""

# localepurge 설치
echo "=== localepurge 설치 ==="
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y localepurge
echo "완료"
echo ""

# 설정 확인
echo "=== 현재 설정 확인 ==="
sudo debconf-show localepurge
echo ""

echo "=========================================="
echo "설치 완료!"
echo "=========================================="
echo ""
echo "localepurge를 실행하려면:"
echo "  sudo localepurge"
echo ""

