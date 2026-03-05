/**
 * 예진이 AI 챗봇 (우송대학교 마스코트)
 * GROQ API 기반 AI 도우미
 */

class AesongChatbot {
    constructor() {
        this.chatHistory = [];
        this.isOpen = false;
        this.ttsEnabled = false;  // 음성출력 ON/OFF 상태
        this.speechSynth = window.speechSynthesis;  // Web Speech API

        // API_BASE_URL 설정
        let baseUrl;
        if (window.API_BASE_URL && window.API_BASE_URL !== '') {
            baseUrl = window.API_BASE_URL;
        } else {
            // 샌드박스 환경 감지: 3000-xxx.sandbox.novita.ai → 8000-xxx.sandbox.novita.ai
            const hostname = window.location.hostname;
            if (hostname.includes('sandbox.novita.ai') || hostname.includes('-')) {
                // 샌드박스 환경: 포트 번호를 서브도메인에서 교체
                baseUrl = window.location.protocol + '//' + hostname.replace(/^3000-/, '8000-');
            } else {
                // 로컬 환경: :8000 포트 사용
                baseUrl = window.location.protocol + '//' + window.location.hostname + ':8000';
            }
        }
        
        this.apiUrl = baseUrl + '/api/aesong-chat';
        // 로컬 이미지 사용 (캐시 무효화를 위한 타임스탬프 추가)
        this.aesongImageUrl = '/aesong-character.png?v=' + Date.now();
        
        console.log('🐶 예진이 챗봇 API URL:', this.apiUrl);
        console.log('🐶 예진이 이미지 URL:', this.aesongImageUrl);
        
        // 애니메이션 배열
        this.animations = ['aesong-bounce', 'aesong-shake', 'aesong-wiggle', 'aesong-float'];
        this.currentAnimation = 0;
        
        this.init();
    }

    init() {
        this.injectStyles();
        this.createChatbotUI();
        this.addSystemPrompt();
        this.startAnimationCycle();
    }
    
    startAnimationCycle() {
        // 5초마다 애니메이션 변경
        setInterval(() => {
            const floatingBtn = document.getElementById('aesong-floating-btn');
            if (floatingBtn) {
                // 이전 애니메이션 제거
                this.animations.forEach(anim => floatingBtn.classList.remove(anim));
                
                // 다음 애니메이션 적용
                this.currentAnimation = (this.currentAnimation + 1) % this.animations.length;
                floatingBtn.classList.add(this.animations[this.currentAnimation]);
            }
        }, 5000);
    }

    injectStyles() {
        const style = document.createElement('style');
        style.textContent = `
            @keyframes bounce {
                0%, 100% { transform: translateY(0); }
                50% { transform: translateY(-10px); }
            }
            
            @keyframes pulse {
                0%, 100% { opacity: 1; }
                50% { opacity: 0.5; }
            }
            
            @keyframes headShake {
                0%, 100% { transform: rotate(0deg); }
                25% { transform: rotate(-8deg); }
                75% { transform: rotate(8deg); }
            }
            
            @keyframes wave {
                0%, 100% { transform: rotate(0deg); }
                10%, 30%, 50%, 70%, 90% { transform: rotate(14deg); }
                20%, 40%, 60%, 80% { transform: rotate(-14deg); }
            }
            
            @keyframes wiggle {
                0%, 100% { transform: translateX(0) rotate(0deg); }
                25% { transform: translateX(-5px) rotate(-5deg); }
                75% { transform: translateX(5px) rotate(5deg); }
            }
            
            @keyframes float {
                0%, 100% { transform: translateY(0px); }
                50% { transform: translateY(-15px); }
            }
            
            .aesong-bounce {
                animation: bounce 2s infinite;
            }
            
            .aesong-pulse {
                animation: pulse 2s infinite;
            }
            
            .aesong-shake {
                animation: headShake 3s infinite;
            }
            
            .aesong-wave {
                animation: wave 2s infinite;
                transform-origin: 70% 70%;
            }
            
            .aesong-wiggle {
                animation: wiggle 3s infinite;
            }
            
            .aesong-float {
                animation: float 3s ease-in-out infinite;
            }
            
            .aesong-chat-open {
                transform: translateY(0) !important;
            }
            
            .aesong-avatar:hover {
                animation: wave 1s ease-in-out;
                cursor: pointer;
            }
            
            .aesong-header-avatar {
                transition: transform 0.3s ease;
            }
            
            .aesong-header-avatar:hover {
                transform: scale(1.1) rotate(10deg);
                cursor: pointer;
            }
            
            #aesong-messages::-webkit-scrollbar {
                width: 6px;
            }
            
            #aesong-messages::-webkit-scrollbar-track {
                background: #f1f1f1;
                border-radius: 10px;
            }
            
            #aesong-messages::-webkit-scrollbar-thumb {
                background: #ec4899;
                border-radius: 10px;
            }
            
            #aesong-messages::-webkit-scrollbar-thumb:hover {
                background: #db2777;
            }
        `;
        document.head.appendChild(style);
    }

    createChatbotUI() {
        const chatbotHTML = `
            <!-- 예진이 플로팅 버튼 -->
            <div id="aesong-floating-btn" class="fixed bottom-6 right-6 z-50 aesong-bounce">
                <button onclick="window.aesongBot.toggle()" 
                        class="bg-gradient-to-br from-pink-400 to-purple-500 hover:from-pink-500 hover:to-purple-600 rounded-full p-3 shadow-2xl transition-all duration-300 hover:scale-110 relative">
                    <img src="${this.aesongImageUrl}" 
                         alt="예진이" 
                         class="w-16 h-16 rounded-full border-4 border-white">
                    <div class="absolute -top-1 -right-1 bg-red-500 text-white text-xs rounded-full w-6 h-6 flex items-center justify-center aesong-pulse">
                        💬
                    </div>
                </button>
            </div>

            <!-- 예진이 챗봇 창 -->
            <div id="aesong-chat" class="fixed bottom-0 right-0 w-full md:w-96 h-[600px] bg-white rounded-t-3xl shadow-2xl transform translate-y-full transition-transform duration-300 z-40">
                <!-- 헤더 -->
                <div class="bg-gradient-to-r from-pink-400 via-purple-400 to-pink-500 p-4 rounded-t-3xl flex items-center justify-between">
                    <div class="flex items-center gap-3">
                        <img src="${this.aesongImageUrl}" 
                             class="w-12 h-12 rounded-full border-2 border-white shadow-lg aesong-header-avatar">
                        <div>
                            <h3 class="text-white font-bold text-lg">예진이</h3>
                            <p class="text-white text-xs flex items-center gap-1">
                                <span class="w-2 h-2 bg-green-400 rounded-full animate-pulse"></span>
                                우송대 AI 도우미 🎓
                            </p>
                        </div>
                    </div>
                    <div class="flex items-center gap-2">
                        <button id="aesong-tts-btn" onclick="window.aesongBot.toggleTTS()"
                                class="text-white hover:bg-white/20 rounded-full p-2 transition-colors" title="음성출력 ON/OFF">
                            <i class="fas fa-volume-mute text-lg" id="aesong-tts-icon"></i>
                        </button>
                        <button onclick="window.aesongBot.toggle()" class="text-white hover:bg-white/20 rounded-full p-2 transition-colors">
                            <i class="fas fa-times text-xl"></i>
                        </button>
                    </div>
                </div>
                
                <!-- 채팅 영역 -->
                <div id="aesong-messages" class="h-[420px] overflow-y-auto p-4 bg-gradient-to-b from-gray-50 to-white">
                    <!-- 초기 인사 메시지 -->
                    <div class="flex gap-3 mb-4 animate-fade-in">
                        <img src="${this.aesongImageUrl}" class="w-10 h-10 rounded-full shadow aesong-avatar">
                        <div class="bg-white p-4 rounded-2xl rounded-tl-none shadow-md max-w-[80%] border border-pink-100">
                            <p class="text-sm text-gray-800 mb-2">안녕하세요! 우송대학교 예진이입니다! 🐶✨</p>
                            <p class="text-sm text-gray-600">
                                훈련일지, 상담일지, 시스템 사용법 등<br>
                                무엇이든 물어보세요!
                            </p>
                            <div class="mt-3 flex flex-wrap gap-2">
                                <button onclick="window.aesongBot.sendQuickQuestion('훈련일지 작성 방법 알려줘')" 
                                        class="bg-pink-100 text-pink-700 px-3 py-1 rounded-full text-xs hover:bg-pink-200 transition-colors">
                                    📝 훈련일지 작성법
                                </button>
                                <button onclick="window.aesongBot.sendQuickQuestion('상담일지는 어떻게 써?')" 
                                        class="bg-purple-100 text-purple-700 px-3 py-1 rounded-full text-xs hover:bg-purple-200 transition-colors">
                                    💬 상담일지 작성법
                                </button>
                            </div>
                        </div>
                    </div>
                </div>
                
                <!-- 입력 영역 -->
                <div class="absolute bottom-0 w-full bg-white border-t border-gray-200 p-4 rounded-b-3xl">
                    <div class="flex gap-2">
                        <input type="text" 
                               id="aesong-input" 
                               placeholder="예진이에게 물어보세요... 🐾"
                               class="flex-1 border border-gray-300 rounded-full px-4 py-3 focus:outline-none focus:ring-2 focus:ring-pink-400 focus:border-transparent"
                               onkeypress="if(event.key==='Enter') window.aesongBot.sendMessage()">
                        <button onclick="window.aesongBot.sendMessage()" 
                                class="bg-gradient-to-r from-pink-500 to-purple-500 text-white rounded-full px-6 py-3 hover:from-pink-600 hover:to-purple-600 transition-all shadow-lg hover:shadow-xl">
                            <i class="fas fa-paper-plane"></i>
                        </button>
                    </div>
                </div>
            </div>
        `;

        document.body.insertAdjacentHTML('beforeend', chatbotHTML);
    }

    addSystemPrompt() {
        this.chatHistory.push({
            role: 'system',
            content: `당신은 우송대학교의 귀여운 마스코트 '예진이'입니다. 🐶

# 당신의 역할
- 바이오헬스AI 실무활용 과정 학생들을 도와주는 친근한 AI 도우미
- 훈련일지, 상담일지, 팀 활동일지, 싸이른메모장 사용법 안내
- 시스템 메뉴 위치, 기능 설명, 문제 해결 지원
- 학습 동기 부여 및 응원

# 말투 특징
- 친근하고 귀여운 말투 (예: "~해요!", "~하면 돼요 🐶")
- 이모지 적극 활용 (🎓, 📝, 💡, ✨, 🐾 등)
- 짧고 명확한 답변 (3-5문장)
- 필요시 단계별 번호 매기기

# 주요 기능 안내
1. **훈련일지** 📝
   - 위치: 메인 메뉴 > 훈련일지 관리
   - 기능: 매일 수업 내용, 학습 내용, 사진 기록
   - 팁: AI 확장하기 버튼으로 자동 작성 가능!

2. **상담일지** 💬
   - 위치: 메인 메뉴 > 상담일지
   - 기능: 학생-강사 상담 내용 기록
   - 팁: 상담 유형별로 분류 가능

3. **싸이른메모장** 📒
   - 위치: 메인 메뉴 > 싸이른메모장
   - 기능: 개인 메모, 일정 관리, 사진 첨부
   - 팁: 실시간 검색으로 빠른 메모 찾기!

4. **팀활동일지** 👥
   - 위치: 메인 메뉴 > 팀활동일지
   - 기능: 프로젝트 활동, 팀 과제 기록

5. **AI 훈련일지** 🤖
   - 위치: 메인 메뉴 > AI 훈련일지
   - 기능: 미작성 일지 자동 생성
   - 팁: 기간 선택 후 일괄 생성 가능!

# 답변 방식
- 질문 파악 → 간단 설명 → 단계별 안내 → 추가 팁
- 메뉴 위치는 구체적으로 알려주기
- 막히면 "제가 도와드릴게요!" 하며 적극 지원

# 금지사항
- 너무 긴 설명 (5문장 이상)
- 어려운 전문 용어
- 부정적이거나 비판적인 표현

항상 밝고 긍정적으로, 학생들이 쉽게 이해할 수 있도록 도와주세요! 🌟`
        });
    }

    toggle() {
        this.isOpen = !this.isOpen;
        const chatWindow = document.getElementById('aesong-chat');

        if (this.isOpen) {
            chatWindow.classList.add('aesong-chat-open');
            // 입력창에 포커스
            setTimeout(() => {
                document.getElementById('aesong-input').focus();
            }, 300);
        } else {
            chatWindow.classList.remove('aesong-chat-open');
            // 창 닫을 때 음성 중지
            this.stopSpeaking();
        }
    }

    // 음성출력 ON/OFF 토글
    toggleTTS() {
        this.ttsEnabled = !this.ttsEnabled;
        const icon = document.getElementById('aesong-tts-icon');
        const btn = document.getElementById('aesong-tts-btn');

        if (this.ttsEnabled) {
            icon.className = 'fas fa-volume-up text-lg';
            btn.title = '음성출력 OFF';
            // 활성화 알림
            this.speakText('음성 출력이 켜졌어요!');
        } else {
            icon.className = 'fas fa-volume-mute text-lg';
            btn.title = '음성출력 ON';
            this.stopSpeaking();
        }
        console.log('🔊 음성출력:', this.ttsEnabled ? 'ON' : 'OFF');
    }

    // 텍스트를 음성으로 출력
    speakText(text) {
        if (!this.ttsEnabled || !this.speechSynth) return;

        // 이전 음성 중지
        this.stopSpeaking();

        // 이모지 및 특수문자 제거
        const cleanText = text.replace(/[\u{1F300}-\u{1F9FF}]|[\u{2600}-\u{26FF}]|[\u{2700}-\u{27BF}]|[*#_~`]/gu, '').trim();

        if (!cleanText) return;

        const utterance = new SpeechSynthesisUtterance(cleanText);
        utterance.lang = 'ko-KR';
        utterance.rate = 1.1;  // 약간 빠르게
        utterance.pitch = 1.2;  // 약간 높은 톤 (귀여운 느낌)

        // 한국어 음성 선택
        const voices = this.speechSynth.getVoices();
        const koreanVoice = voices.find(v => v.lang.includes('ko'));
        if (koreanVoice) {
            utterance.voice = koreanVoice;
        }

        this.speechSynth.speak(utterance);
    }

    // 음성 중지
    stopSpeaking() {
        if (this.speechSynth) {
            this.speechSynth.cancel();
        }
    }

    async sendMessage() {
        const input = document.getElementById('aesong-input');
        const message = input.value.trim();
        
        if (!message) return;
        
        // 입력창 초기화
        input.value = '';
        
        // 사용자 메시지 표시
        this.addMessageToUI('user', message);
        
        // 채팅 히스토리에 추가
        this.chatHistory.push({
            role: 'user',
            content: message
        });
        
        // 로딩 표시
        this.addLoadingMessage();
        
        try {
            // 백엔드 API 호출 (GROQ API는 백엔드에서 처리)
            const response = await fetch(this.apiUrl, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    message: message,
                    character: '예진이',
                    model: 'groq'
                })
            });
            
            if (!response.ok) {
                throw new Error(`API 오류: ${response.status}`);
            }
            
            const data = await response.json();
            const aiResponse = data.response;
            
            // 로딩 제거
            this.removeLoadingMessage();

            // AI 응답 표시
            this.addMessageToUI('ai', aiResponse);

            // 음성 출력 (TTS가 켜져 있으면)
            this.speakText(aiResponse);

            // 채팅 히스토리에 추가
            this.chatHistory.push({
                role: 'assistant',
                content: aiResponse
            });
            
        } catch (error) {
            console.error('예진이 챗봇 오류:', error);
            this.removeLoadingMessage();
            this.addMessageToUI('ai', '아이고! 일시적인 문제가 발생했어요 😢\n잠시 후 다시 시도해주세요!');
        }
    }

    sendQuickQuestion(question) {
        const input = document.getElementById('aesong-input');
        input.value = question;
        this.sendMessage();
    }

    addMessageToUI(type, message) {
        const messagesDiv = document.getElementById('aesong-messages');
        
        const messageDiv = document.createElement('div');
        messageDiv.className = 'flex gap-3 mb-4 animate-fade-in ' + (type === 'user' ? 'justify-end' : '');
        
        if (type === 'ai') {
            messageDiv.innerHTML = `
                <img src="${this.aesongImageUrl}" class="w-10 h-10 rounded-full shadow aesong-avatar">
                <div class="bg-white p-3 rounded-2xl rounded-tl-none shadow-md max-w-[80%] border border-pink-100">
                    <p class="text-sm text-gray-800 whitespace-pre-wrap">${this.escapeHtml(message)}</p>
                </div>
            `;
        } else {
            messageDiv.innerHTML = `
                <div class="bg-gradient-to-r from-pink-500 to-purple-500 text-white p-3 rounded-2xl rounded-tr-none shadow-md max-w-[80%]">
                    <p class="text-sm whitespace-pre-wrap">${this.escapeHtml(message)}</p>
                </div>
            `;
        }
        
        messagesDiv.appendChild(messageDiv);
        messagesDiv.scrollTop = messagesDiv.scrollHeight;
    }

    addLoadingMessage() {
        const messagesDiv = document.getElementById('aesong-messages');
        const loadingDiv = document.createElement('div');
        loadingDiv.id = 'aesong-loading';
        loadingDiv.className = 'flex gap-3 mb-4';
        loadingDiv.innerHTML = `
            <img src="${this.aesongImageUrl}" class="w-10 h-10 rounded-full shadow aesong-avatar aesong-wiggle">
            <div class="bg-white p-4 rounded-2xl shadow-md">
                <div class="flex gap-1">
                    <div class="w-2 h-2 bg-pink-400 rounded-full animate-bounce"></div>
                    <div class="w-2 h-2 bg-pink-400 rounded-full animate-bounce" style="animation-delay: 0.1s"></div>
                    <div class="w-2 h-2 bg-pink-400 rounded-full animate-bounce" style="animation-delay: 0.2s"></div>
                </div>
            </div>
        `;
        messagesDiv.appendChild(loadingDiv);
        messagesDiv.scrollTop = messagesDiv.scrollHeight;
    }

    removeLoadingMessage() {
        const loading = document.getElementById('aesong-loading');
        if (loading) loading.remove();
    }

    escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }
}

// 전역 인스턴스 생성
document.addEventListener('DOMContentLoaded', () => {
    window.aesongBot = new AesongChatbot();
    console.log('🐶 예진이 챗봇이 준비되었습니다!');
});
