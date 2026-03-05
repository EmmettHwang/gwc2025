const http = require('http');
const fs = require('fs');
const path = require('path');
const { URL } = require('url');

const PORT = 3000;
const BACKEND_URL = 'http://localhost:8000';

const mimeTypes = {
    '.html': 'text/html',
    '.js': 'text/javascript',
    '.css': 'text/css',
    '.json': 'application/json',
    '.png': 'image/png',
    '.jpg': 'image/jpg',
    '.gif': 'image/gif',
    '.svg': 'image/svg+xml',
    '.ico': 'image/x-icon',
    '.glb': 'model/gltf-binary',
    '.gltf': 'model/gltf+json'
};

const server = http.createServer((req, res) => {
    console.log(`${req.method} ${req.url}`);

    // /api/ 요청은 백엔드로 프록시
    if (req.url.startsWith('/api/')) {
        const proxyReq = http.request({
            hostname: 'localhost',
            port: 8000,
            path: req.url,
            method: req.method,
            headers: req.headers
        }, (proxyRes) => {
            res.writeHead(proxyRes.statusCode, proxyRes.headers);
            proxyRes.pipe(res);
        });

        proxyReq.on('error', (err) => {
            console.error('Proxy error:', err);
            res.writeHead(500, { 'Content-Type': 'text/plain' });
            res.end('Proxy error');
        });

        req.pipe(proxyReq);
        return;
    }

    // 정적 파일 서빙 - 쿼리 스트링 제거
    const urlPath = req.url.split('?')[0]; // 쿼리 스트링 제거
    
    // .glb 파일은 dist 폴더에서 찾기
    let filePath;
    if (urlPath.endsWith('.glb') || urlPath.endsWith('.gltf')) {
        filePath = path.join(__dirname, '..', 'dist', urlPath);
    } else {
        filePath = path.join(__dirname, urlPath);
    }
    
    // 루트 경로는 데스크탑 index.html로
    if (urlPath === '/') {
        filePath = path.join(__dirname, 'index.html');
    }
    // /mobile/ 경로는 mobile/index.html로
    else if (urlPath === '/mobile' || urlPath === '/mobile/') {
        filePath = path.join(__dirname, 'mobile', 'index.html');
    }
    // 디렉토리 경로에 index.html 자동 추가
    else if (fs.existsSync(filePath) && fs.statSync(filePath).isDirectory()) {
        filePath = path.join(filePath, 'index.html');
    }

    const extname = String(path.extname(filePath)).toLowerCase();
    const contentType = mimeTypes[extname] || 'application/octet-stream';

    fs.readFile(filePath, (error, content) => {
        if (error) {
            if (error.code === 'ENOENT') {
                res.writeHead(404, { 'Content-Type': 'text/html' });
                res.end('<h1>404 Not Found</h1>', 'utf-8');
            } else {
                res.writeHead(500);
                res.end('Server Error: ' + error.code);
            }
        } else {
            res.writeHead(200, { 'Content-Type': contentType });
            res.end(content, 'utf-8');
        }
    });
});

server.listen(PORT, '0.0.0.0', () => {
    console.log(`✅ 프록시 서버가 포트 ${PORT}에서 실행 중입니다`);
    console.log(`   - 정적 파일: http://localhost:${PORT}`);
    console.log(`   - API 프록시: ${BACKEND_URL}`);
});
