#!/usr/bin/env python3
"""
PWA 아이콘 생성 스크립트
간단한 파란색 배경에 "BH" 텍스트가 있는 아이콘을 생성합니다.
"""

from PIL import Image, ImageDraw, ImageFont
import os

# 아이콘 크기 목록
ICON_SIZES = [72, 96, 128, 144, 152, 192, 384, 512]

# 색상 설정
BG_COLOR = (59, 130, 246)  # Tailwind blue-500 (#3B82F6)
TEXT_COLOR = (255, 255, 255)  # White

def create_icon(size):
    """지정된 크기의 아이콘 생성"""
    
    # 이미지 생성 (파란색 배경)
    img = Image.new('RGB', (size, size), color=BG_COLOR)
    draw = ImageDraw.Draw(img)
    
    # 텍스트 크기 계산 (아이콘 크기의 40%)
    font_size = int(size * 0.4)
    
    try:
        # 시스템 폰트 사용 (굵은 폰트)
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", font_size)
    except:
        # 폰트를 찾지 못하면 기본 폰트 사용
        font = ImageFont.load_default()
    
    # 텍스트 그리기
    text = "BH"
    
    # 텍스트 중앙 정렬 (PIL 9.2.0+ 방식)
    bbox = draw.textbbox((0, 0), text, font=font)
    text_width = bbox[2] - bbox[0]
    text_height = bbox[3] - bbox[1]
    
    x = (size - text_width) / 2 - bbox[0]
    y = (size - text_height) / 2 - bbox[1]
    
    draw.text((x, y), text, fill=TEXT_COLOR, font=font)
    
    # 둥근 모서리 추가 (선택사항)
    # 마스크 생성
    mask = Image.new('L', (size, size), 0)
    mask_draw = ImageDraw.Draw(mask)
    mask_draw.rounded_rectangle([(0, 0), (size, size)], radius=size//8, fill=255)
    
    # 둥근 모서리 적용
    output = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    output.paste(img, (0, 0))
    output.putalpha(mask)
    
    return output

def main():
    """모든 크기의 아이콘 생성"""
    
    print("🎨 PWA 아이콘 생성 중...")
    
    # 현재 디렉토리 확인
    current_dir = os.path.dirname(os.path.abspath(__file__))
    print(f"📂 저장 위치: {current_dir}")
    
    # 각 크기별 아이콘 생성
    for size in ICON_SIZES:
        filename = f"icon-{size}x{size}.png"
        filepath = os.path.join(current_dir, filename)
        
        print(f"  ✅ {filename} 생성 중...")
        
        icon = create_icon(size)
        icon.save(filepath, 'PNG')
        
        print(f"     크기: {size}x{size} | 저장됨: {filepath}")
    
    # Badge 아이콘 생성 (알림용)
    print(f"  ✅ badge-72x72.png 생성 중...")
    badge = create_icon(72)
    badge.save(os.path.join(current_dir, "badge-72x72.png"), 'PNG')
    
    # Favicon 생성
    print(f"  ✅ favicon.ico 생성 중...")
    favicon = create_icon(32)
    favicon.save(os.path.join(current_dir, "favicon.ico"), 'ICO')
    
    print("\n✨ 모든 아이콘 생성 완료!")
    print(f"📦 총 {len(ICON_SIZES) + 2}개 파일 생성됨")
    print("\n💡 다음 단계:")
    print("   1. index.html에 manifest.json 링크 추가")
    print("   2. Service Worker 등록")
    print("   3. HTTPS로 배포")

if __name__ == '__main__':
    main()
