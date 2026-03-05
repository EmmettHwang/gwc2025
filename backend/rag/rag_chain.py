"""
RAG 체인 모듈
검색된 문서를 기반으로 AI 응답 생성
"""

from typing import List, Dict, Optional
import httpx

# LangChain imports - 버전 호환성 처리
try:
    from langchain_core.documents import Document
except ImportError:
    from langchain.schema import Document


class RAGChain:
    """RAG 체인 클래스"""
    
    def __init__(self, vector_store_manager, api_key: str, api_type: str = "groq"):
        """
        Args:
            vector_store_manager: VectorStoreManager 인스턴스
            api_key: AI API 키 (GROQ, Gemini 등)
            api_type: API 타입 ('groq', 'gemini', 'gemma')
        """
        self.vector_store = vector_store_manager
        self.api_key = api_key
        self.api_type = api_type.lower()
    
    def _format_context(self, documents: List[Document]) -> str:
        """
        검색된 문서들을 컨텍스트로 포맷팅
        
        Args:
            documents: 검색된 Document 리스트
            
        Returns:
            포맷된 컨텍스트 문자열
        """
        if not documents:
            return "관련 문서를 찾을 수 없습니다."
        
        context_parts = []
        for i, doc in enumerate(documents, 1):
            source = doc.metadata.get('source', '알 수 없음')
            content = doc.page_content.strip()
            
            context_parts.append(f"[문서 {i}] 출처: {source}\n{content}")
        
        return "\n\n".join(context_parts)
    
    def _build_prompt(self, query: str, context: str, system_message: Optional[str] = None) -> str:
        """
        RAG 프롬프트 생성 (개선된 버전)
        
        Args:
            query: 사용자 질문
            context: 검색된 문서 컨텍스트
            system_message: 시스템 메시지 (선택)
            
        Returns:
            완성된 프롬프트
        """
        if system_message is None:
            system_message = """당신은 바이오헬스 분야 전문 교육 어시스턴트입니다.
제공된 문서를 기반으로 정확하고 간결하게 답변해주세요."""
        
        prompt = f"""{system_message}

=== 참고 문서 ===
{context}

=== 질문 ===
{query}

=== 답변 규칙 ===
1. 문서에 명확한 답이 있으면 정확히 인용하여 답변하세요
2. 문서에 답이 없으면 "죄송합니다. 제공된 문서에서 관련 정보를 찾을 수 없습니다"라고 명시하세요
3. 추측하거나 같은 내용을 반복하지 마세요
4. 구체적인 숫자나 데이터가 있으면 반드시 포함하세요
5. 간결하고 명확하게 답변하세요 (불필요한 반복 금지)

=== 답변 ===
"""
        
        return prompt
    
    async def _call_groq_api(self, prompt: str) -> str:
        """GROQ API 호출"""
        url = "https://api.groq.com/openai/v1/chat/completions"
        
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "model": "llama-3.3-70b-versatile",
            "messages": [
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.3,  # 정확도 우선
            "max_tokens": 8000,  # 문제 생성 등 긴 응답을 위해 증가
            "top_p": 0.9
        }

        async with httpx.AsyncClient() as client:
            response = await client.post(url, headers=headers, json=payload, timeout=120.0)  # 타임아웃 증가
            response.raise_for_status()
            data = response.json()
            
            if data.get('choices'):
                return data['choices'][0]['message']['content']
            else:
                return "응답을 생성할 수 없습니다."
    
    async def _call_gemini_api(self, prompt: str) -> str:
        """Gemini API 호출"""
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash-exp:generateContent?key={self.api_key}"
        
        headers = {
            "Content-Type": "application/json"
        }
        
        payload = {
            "contents": [{
                "parts": [{"text": prompt}]
            }],
            "generationConfig": {
                "temperature": 0.3,
                "maxOutputTokens": 1000,
                "topP": 0.9
            }
        }
        
        async with httpx.AsyncClient() as client:
            response = await client.post(url, headers=headers, json=payload, timeout=30.0)
            response.raise_for_status()
            data = response.json()
            
            if data.get('candidates'):
                return data['candidates'][0]['content']['parts'][0]['text']
            else:
                return "응답을 생성할 수 없습니다."
    
    async def query(self,
                    question: str,
                    k: int = 5,  # 3에서 5로 증가
                    system_message: Optional[str] = None,
                    min_similarity: float = 0.3,  # 최소 유사도 임계값 추가
                    document_context: Optional[List[str]] = None,  # 특정 문서로 제한
                    groq_api_key: Optional[str] = None) -> Dict:  # API 키 동적 전달
        """
        RAG 질문 처리 (개선된 버전)

        Args:
            question: 사용자 질문
            k: 검색할 문서 수 (기본값 5로 증가)
            system_message: 커스텀 시스템 메시지
            min_similarity: 최소 유사도 임계값 (0.0~1.0, 기본값 0.3)
            document_context: 특정 문서명 목록으로 필터링 (선택)
            groq_api_key: GROQ API 키 (선택, 동적 전달)

        Returns:
            {
                'answer': AI 응답,
                'sources': 참고 문서 리스트,
                'context': 검색된 컨텍스트
            }
        """
        # API 키가 전달되면 사용
        if groq_api_key:
            self.api_key = groq_api_key

        try:
            # 1. 관련 문서 검색
            print(f"[DEBUG] 질문: {question[:100]}...")
            print(f"[DOC] {k}개 문서 검색 중...")

            documents = self.vector_store.search_with_score(question, k=k * 2 if document_context else k)

            # 문서 컨텍스트가 지정된 경우 필터링
            if document_context and len(document_context) > 0:
                print(f"[FILTER] {len(document_context)}개 문서로 필터링: {document_context}")
                filtered_docs = []
                for doc in documents:
                    metadata = doc.get('metadata', {})
                    filename = metadata.get('original_filename') or metadata.get('filename', '')
                    # 파일명이 선택된 문서 목록에 포함되어 있는지 확인
                    if any(ctx in filename or filename in ctx for ctx in document_context):
                        filtered_docs.append(doc)
                documents = filtered_docs[:k]
                print(f"[FILTER] 필터링 후 {len(documents)}개 문서")
            
            if not documents:
                return {
                    'answer': "죄송합니다. 관련 문서를 찾을 수 없습니다. 문서를 업로드하거나 다른 질문을 시도해보세요.",
                    'sources': [],
                    'context': ""
                }
            
            # 2. 유사도 체크 - 모든 문서의 유사도가 너무 낮으면 경고
            max_similarity = max([doc_dict.get('score', 0) for doc_dict in documents])
            print(f"[INFO] 최대 유사도: {max_similarity:.2%}")
            
            if max_similarity < min_similarity:
                return {
                    'answer': f"죄송합니다. 질문과 관련된 정보를 문서에서 찾을 수 없습니다.\n\n💡 팁: 다른 키워드로 질문하거나, 더 구체적으로 질문해주세요.\n(검색된 문서의 최대 유사도: {max_similarity:.1%})",
                    'sources': [],
                    'context': ""
                }
            
            # 3. 컨텍스트 포맷팅 (SimpleVectorStore 형식)
            context_parts = []
            for i, doc_dict in enumerate(documents, 1):
                metadata = doc_dict.get('metadata', {})
                source = metadata.get('original_filename') or metadata.get('filename', '알 수 없음')
                subject = metadata.get('subject', '')
                content = doc_dict.get('content', '').strip()
                similarity = doc_dict.get('score', 0)
                
                source_info = f"{source}"
                if subject:
                    source_info += f" ({subject})"
                
                context_parts.append(f"[문서 {i}] 출처: {source_info} (유사도: {similarity:.1%})\n{content}")
            
            context = "\n\n".join(context_parts)
            
            print(f"[OK] {len(documents)}개 문서 검색 완료")
            
            # 4. 프롬프트 생성
            prompt = self._build_prompt(question, context, system_message)
            
            # 5. AI API 호출
            print(f"[AI] {self.api_type.upper()} API 호출 중...")
            
            if self.api_type == 'groq' or self.api_type == 'gemma':
                answer = await self._call_groq_api(prompt)
            elif self.api_type == 'gemini':
                answer = await self._call_gemini_api(prompt)
            else:
                answer = "지원하지 않는 API 타입입니다."
            
            print(f"[OK] 응답 생성 완료")
            
            # 6. 출처 정보 추출 (SimpleVectorStore 형식)
            sources = []
            for doc_dict in documents:
                metadata = doc_dict.get('metadata', {})
                source_name = metadata.get('original_filename') or metadata.get('filename', '알 수 없음')
                subject = metadata.get('subject', '')
                
                source_display = source_name
                if subject:
                    source_display = f"{source_name} - {subject}"
                
                sources.append({
                    'source': source_display,
                    'content': doc_dict.get('content', '')[:200] + '...',
                    'similarity': float(doc_dict.get('score', 0)),  # 0~1 범위로 반환
                    'metadata': metadata
                })
            
            return {
                'answer': answer,
                'sources': sources,
                'context': context
            }
            
        except Exception as e:
            print(f"[ERROR] RAG 질문 처리 실패: {e}")
            return {
                'answer': f"오류가 발생했습니다: {str(e)}",
                'sources': [],
                'context': ""
            }
    
    async def query_simple(self, question: str, k: int = 3) -> str:
        """
        간단한 RAG 질문 (답변만 반환)
        
        Args:
            question: 사용자 질문
            k: 검색할 문서 수
            
        Returns:
            AI 응답 문자열
        """
        result = await self.query(question, k=k)
        return result['answer']


if __name__ == "__main__":
    import asyncio
    import os
    from document_loader import DocumentLoader
    from vector_store import VectorStoreManager
    
    async def test_rag():
        # 문서 로더
        loader = DocumentLoader(chunk_size=500, chunk_overlap=50)
        
        # 샘플 문서
        sample_text = """
        바이오헬스 산업 개요
        
        바이오헬스 산업은 생명공학 기술을 활용하여 인간의 건강과 삶의 질을 향상시키는 산업입니다.
        주요 분야로는 신약 개발, 의료기기, 디지털 헬스케어 등이 있습니다.
        
        mRNA 백신 기술
        
        mRNA 백신은 메신저 RNA를 이용하여 우리 몸의 세포가 특정 단백질을 생성하도록 지시합니다.
        이 기술은 COVID-19 팬데믹 동안 빠르게 발전하였으며, 향후 암 치료 등에도 활용될 전망입니다.
        """
        
        os.makedirs("./test_docs", exist_ok=True)
        with open("./test_docs/sample.txt", "w", encoding="utf-8") as f:
            f.write(sample_text)
        
        # 문서 로드
        docs = loader.load_document("./test_docs/sample.txt", {"subject": "바이오헬스 기초"})
        
        # 벡터 스토어
        vector_store = VectorStoreManager(
            persist_directory="./test_chroma_db",
            collection_name="test_collection"
        )
        vector_store.add_documents(docs)
        
        # RAG 체인 (API 키 필요)
        api_key = os.getenv("GROQ_API_KEY", "your-api-key-here")
        rag_chain = RAGChain(vector_store, api_key, api_type="groq")
        
        # 질문
        question = "mRNA 백신이 무엇인가요?"
        print(f"\n[Q] 질문: {question}\n")
        
        result = await rag_chain.query(question, k=2)
        
        print(f"\n[AI] 답변:\n{result['answer']}\n")
        print(f"\n[DOC] 참고 문서:")
        for i, source in enumerate(result['sources'], 1):
            print(f"\n  {i}. {source['source']} (유사도: {source['similarity']:.4f})")
            print(f"     {source['content']}")
    
    # 실행
    asyncio.run(test_rag())
