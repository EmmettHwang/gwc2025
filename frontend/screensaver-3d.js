import * as THREE from 'three';

// Three.js 3D 화면보호기 (Sprite 방식)
let scene, camera, renderer, sprite, clock;
let isAnimating = false;

async function init3DScreensaver() {
    const canvas = document.getElementById('threejs-canvas');
    if (!canvas) {
        console.error('Canvas not found!');
        return;
    }

    console.log('🚀 Initializing 3D Screensaver (Sprite mode)...');

    // Scene 설정
    scene = new THREE.Scene();
    
    // Camera 설정
    camera = new THREE.PerspectiveCamera(50, window.innerWidth / window.innerHeight, 0.1, 1000);
    camera.position.z = 5;
    
    // Renderer 설정
    renderer = new THREE.WebGLRenderer({ 
        canvas: canvas, 
        alpha: true, 
        antialias: true 
    });
    renderer.setSize(window.innerWidth, window.innerHeight);
    renderer.setPixelRatio(window.devicePixelRatio);
    
    // 조명 설정
    const ambientLight = new THREE.AmbientLight(0xffffff, 0.8);
    scene.add(ambientLight);
    
    const pointLight1 = new THREE.PointLight(0xff69b4, 2, 100);
    pointLight1.position.set(-3, 3, 3);
    scene.add(pointLight1);
    
    const pointLight2 = new THREE.PointLight(0xffb6c1, 2, 100);
    pointLight2.position.set(3, 3, -3);
    scene.add(pointLight2);
    
    console.log('💡 Lights added');
    
    // 텍스처 로드
    const textureLoader = new THREE.TextureLoader();
    try {
        console.log('🖼️  Loading texture: /aesong-character.png');
        
        const texture = await new Promise((resolve, reject) => {
            textureLoader.load('/aesong-character.png', resolve, undefined, reject);
        });
        
        // Sprite 생성
        const spriteMaterial = new THREE.SpriteMaterial({ 
            map: texture,
            transparent: true,
            opacity: 1.0
        });
        
        sprite = new THREE.Sprite(spriteMaterial);
        sprite.scale.set(2, 2, 1);
        scene.add(sprite);
        
        console.log('✅ Sprite created successfully!');
        
    } catch (error) {
        console.error('❌ Error loading texture:', error);
    }
    
    clock = new THREE.Clock();
    
    // 리사이즈 핸들러
    window.addEventListener('resize', onWindowResize, false);
    
    // 애니메이션 시작
    isAnimating = true;
    animate();
    
    console.log('🎪 Animation started!');
}

function animate() {
    if (!isAnimating) return;
    
    requestAnimationFrame(animate);
    
    const delta = clock.getDelta();
    const time = clock.getElapsedTime();
    
    if (sprite) {
        // 부드러운 회전
        sprite.material.rotation = time * 0.5;
        
        // 위아래로 떠다니는 효과
        sprite.position.y = Math.sin(time * 0.8) * 0.5;
        
        // 좌우로 흔들리는 효과
        sprite.position.x = Math.sin(time * 0.5) * 1.5;
        sprite.position.z = Math.cos(time * 0.5) * 0.3;
        
        // 크기 변화
        const scaleBase = 2;
        const scaleVariation = Math.sin(time * 0.6) * 0.3;
        sprite.scale.set(
            scaleBase + scaleVariation, 
            scaleBase + scaleVariation, 
            1
        );
        
        // 투명도 변화
        sprite.material.opacity = 0.9 + Math.sin(time * 0.4) * 0.1;
    }
    
    // 조명 애니메이션
    if (scene.children.length > 1) {
        const pointLight1 = scene.children[1];
        const pointLight2 = scene.children[2];
        
        if (pointLight1 && pointLight1.isLight) {
            pointLight1.intensity = 2 + Math.sin(time * 2) * 0.5;
        }
        if (pointLight2 && pointLight2.isLight) {
            pointLight2.intensity = 2 + Math.cos(time * 2) * 0.5;
        }
    }
    
    renderer.render(scene, camera);
}

function onWindowResize() {
    camera.aspect = window.innerWidth / window.innerHeight;
    camera.updateProjectionMatrix();
    renderer.setSize(window.innerWidth, window.innerHeight);
}

function stop3DScreensaver() {
    console.log('🛑 Stopping 3D Screensaver');
    isAnimating = false;
    if (renderer) {
        renderer.dispose();
    }
}

// Export functions
window.init3DScreensaver = init3DScreensaver;
window.stop3DScreensaver = stop3DScreensaver;

console.log('📜 screensaver-3d.js loaded (Sprite mode)');
