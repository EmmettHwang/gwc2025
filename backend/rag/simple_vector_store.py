"""
간소화된 RAG 벡터 스토어 (FAISS 기반, ChromaDB 없이)
Python 3.14 호환
"""
import os
import pickle
from typing import List, Dict, Any, Optional
from sentence_transformers import SentenceTransformer
import faiss
import numpy as np


class SimpleVectorStore:
    """FAISS 기반 간단한 벡터 스토어"""
    
    def __init__(
        self,
        collection_name: str = "documents",
        persist_directory: str = "./simple_vector_db",
        embedding_model: str = "jhgan/ko-sroberta-multitask"
    ):
        self.collection_name = collection_name
        
        # Windows 한글 경로 문제 해결: ASCII 경로로 강제 변환
        import sys
        import tempfile
        from pathlib import Path
        
        if sys.platform == "win32":
            # Windows: C:/Users/USERNAME/AppData/Local/Temp 사용
            safe_persist_dir = Path(tempfile.gettempdir()) / "bh2025_vector_db"
        else:
            # Linux/Mac: 원래 경로 사용
            safe_persist_dir = Path(persist_directory)
        
        self.persist_directory = str(safe_persist_dir)
        self.embedding_model_name = embedding_model
        
        # 디렉토리 생성
        os.makedirs(self.persist_directory, exist_ok=True)
        print(f"[INFO] 벡터 DB 경로: {self.persist_directory}")
        
        # 모델 캐시 디렉토리 설정 (프로젝트 내부)
        model_cache_dir = "./backend/model_cache"
        os.makedirs(model_cache_dir, exist_ok=True)
        
        # 임베딩 모델 로드 (로컬 캐시 사용)
        print(f"[INFO] 임베딩 모델 로드 중: {embedding_model}")
        print(f"[INFO] Model cache path: {model_cache_dir}")
        self.embedding_model = SentenceTransformer(
            embedding_model,
            cache_folder=model_cache_dir
        )
        self.embedding_dimension = self.embedding_model.get_sentence_embedding_dimension()
        
        # FAISS 인덱스 초기화
        self.index = faiss.IndexFlatL2(self.embedding_dimension)
        
        # 문서 메타데이터 저장
        self.documents = []
        self.metadatas = []
        
        # 저장된 인덱스 로드 시도
        self._load_index()
        
        print(f"[OK] 벡터 스토어 초기화 완료 (문서 수: {len(self.documents)})")
    
    def add_documents(
        self,
        texts: List[str],
        metadatas: Optional[List[Dict[str, Any]]] = None
    ) -> List[str]:
        """문서 추가"""
        if metadatas is None:
            metadatas = [{}] * len(texts)
        
        # 임베딩 생성
        print(f"[INFO] {len(texts)}개 문서 임베딩 생성 중...")
        embeddings = self.embedding_model.encode(
            texts,
            show_progress_bar=True,
            convert_to_numpy=True
        )
        
        # FAISS 인덱스에 추가
        self.index.add(embeddings.astype('float32'))
        
        # 문서와 메타데이터 저장
        document_ids = []
        for i, (text, metadata) in enumerate(zip(texts, metadatas)):
            doc_id = f"doc_{len(self.documents) + i}"
            document_ids.append(doc_id)
            
            self.documents.append(text)
            self.metadatas.append({
                **metadata,
                "document_id": doc_id
            })
        
        # 인덱스 저장
        self._save_index()
        
        print(f"[OK] {len(texts)}개 문서 추가 완료")
        return document_ids
    
    def similarity_search(
        self,
        query: str,
        k: int = 3
    ) -> List[Dict[str, Any]]:
        """유사도 검색"""
        if len(self.documents) == 0:
            return []
        
        # 쿼리 임베딩 생성
        query_embedding = self.embedding_model.encode(
            [query],
            convert_to_numpy=True
        ).astype('float32')
        
        # FAISS 검색
        distances, indices = self.index.search(query_embedding, min(k, len(self.documents)))
        
        # 결과 포맷팅
        results = []
        for distance, idx in zip(distances[0], indices[0]):
            if idx < len(self.documents):
                results.append({
                    "content": self.documents[idx],
                    "metadata": self.metadatas[idx],
                    "score": float(1 / (1 + distance))  # 거리를 유사도로 변환
                })
        
        return results
    
    def get_all_documents(self) -> List[Dict[str, Any]]:
        """모든 문서 조회"""
        return [
            {
                "content": doc,
                "metadata": meta
            }
            for doc, meta in zip(self.documents, self.metadatas)
        ]
    
    def clear(self):
        """모든 데이터 삭제"""
        self.index = faiss.IndexFlatL2(self.embedding_dimension)
        self.documents = []
        self.metadatas = []
        self._save_index()
        print("[OK] 벡터 스토어 초기화 완료")
    
    def count(self) -> int:
        """문서 개수"""
        return len(self.documents)
    
    def _save_index(self):
        """인덱스 저장"""
        index_path = os.path.join(self.persist_directory, f"{self.collection_name}.index")
        metadata_path = os.path.join(self.persist_directory, f"{self.collection_name}.pkl")
        
        # FAISS 인덱스 저장
        faiss.write_index(self.index, index_path)
        
        # 메타데이터 저장
        with open(metadata_path, 'wb') as f:
            pickle.dump({
                'documents': self.documents,
                'metadatas': self.metadatas,
                'embedding_model': self.embedding_model_name
            }, f)
    
    def _load_index(self):
        """저장된 인덱스 로드"""
        index_path = os.path.join(self.persist_directory, f"{self.collection_name}.index")
        metadata_path = os.path.join(self.persist_directory, f"{self.collection_name}.pkl")
        
        if os.path.exists(index_path) and os.path.exists(metadata_path):
            try:
                # FAISS 인덱스 로드
                self.index = faiss.read_index(index_path)
                
                # 메타데이터 로드
                with open(metadata_path, 'rb') as f:
                    data = pickle.load(f)
                    self.documents = data['documents']
                    self.metadatas = data['metadatas']
                
                print(f"[OK] 저장된 인덱스 로드 완료 (문서 수: {len(self.documents)})")
            except Exception as e:
                print(f"[WARN]  인덱스 로드 실패: {e}")
                print("새 인덱스를 생성합니다.")
