"""
벡터 스토어 관리 모듈
FAISS를 사용하여 문서 임베딩 저장 및 검색 (Python 3.14 호환)
"""

import os
from typing import List, Dict, Optional
from .simple_vector_store import SimpleVectorStore


class VectorStoreManager:
    """벡터 스토어 관리 클래스 (간소화 버전)"""
    
    def __init__(self, 
                 persist_directory: str = "./simple_vector_db",
                 collection_name: str = "biohealth_docs",
                 embedding_model: str = "jhgan/ko-sroberta-multitask"):
        """
        Args:
            persist_directory: 벡터 DB 저장 디렉토리
            collection_name: 컬렉션 이름
            embedding_model: 임베딩 모델 (한국어 지원)
        """
        self.persist_directory = persist_directory
        self.collection_name = collection_name
        self.embedding_model = embedding_model
        
        # SimpleVectorStore 초기화
        self.vectorstore = SimpleVectorStore(
            collection_name=collection_name,
            persist_directory=persist_directory,
            embedding_model=embedding_model
        )
        
        print(f"[OK] 벡터 스토어 초기화 완료 (문서 수: {self.vectorstore.count()})")
    
    def add_documents(self, texts: List[str], metadatas: List[Dict] = None) -> List[str]:
        """
        문서 추가
        
        Args:
            texts: 문서 텍스트 리스트
            metadatas: 메타데이터 리스트
            
        Returns:
            추가된 문서 ID 리스트
        """
        if not texts:
            print("[WARN] 추가할 문서가 없습니다")
            return []
        
        print(f"📝 {len(texts)}개 문서 추가 중...")
        
        try:
            ids = self.vectorstore.add_documents(texts, metadatas)
            print(f"[OK] {len(ids)}개 문서 추가 완료")
            return ids
            
        except Exception as e:
            print(f"[ERROR] 문서 추가 실패: {e}")
            return []
    
    def search(self, 
               query: str, 
               k: int = 3) -> List[Dict]:
        """
        유사도 검색
        
        Args:
            query: 검색 쿼리
            k: 반환할 문서 수
            
        Returns:
            유사한 문서 리스트
        """
        try:
            results = self.vectorstore.similarity_search(query, k=k)
            print(f"[DEBUG] 검색 완료: {len(results)}개 문서")
            return results
            
        except Exception as e:
            print(f"[ERROR] 검색 실패: {e}")
            return []
    
    def search_with_score(self, 
                          query: str, 
                          k: int = 3) -> List[Dict]:
        """
        유사도 점수와 함께 검색
        
        Args:
            query: 검색 쿼리
            k: 반환할 문서 수
            
        Returns:
            문서와 점수 리스트
        """
        return self.search(query, k)
    
    def get_all_documents(self) -> List[Dict]:
        """
        모든 문서 조회
        
        Returns:
            모든 문서 리스트
        """
        try:
            documents = self.vectorstore.get_all_documents()
            print(f"[DOC] 총 {len(documents)}개 문서")
            return documents
            
        except Exception as e:
            print(f"[ERROR] 문서 조회 실패: {e}")
            return []
    
    def count_documents(self) -> int:
        """
        문서 개수 조회
        
        Returns:
            총 문서 개수
        """
        return self.vectorstore.count()
    
    def clear(self):
        """벡터 스토어 초기화 (모든 데이터 삭제)"""
        try:
            self.vectorstore.clear()
            print("[OK] 벡터 스토어 초기화 완료")
        except Exception as e:
            print(f"[ERROR] 벡터 스토어 초기화 실패: {e}")
    
    def delete_collection(self):
        """컬렉션 삭제"""
        self.clear()
