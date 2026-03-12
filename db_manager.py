import json
import logging
from typing import List, Dict, Any, Optional
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct, Filter, FieldCondition, MatchValue
from fastembed import TextEmbedding

logger = logging.getLogger(__name__)

class DBManager:
    """
    Qdrantを用いたローカルベクトルデータベース管理クラス。
    各ターンのイベントや秘密情報を保存し、アクセス制御付きでRAG検索を提供する。
    """
    def __init__(self, db_path: str = "./db", collection_name: str = "diplomacy_events"):
        self.db_path = db_path
        self.collection_name = collection_name
        
        # Qdrantクライアントの初期化 (ローカルファイルモード)
        # docker不要でPythonから直接読み書き可能
        try:
            self.client = QdrantClient(path=self.db_path)
            logger.info(f"Qdrant client initialized at: {self.db_path}")
        except Exception as e:
            logger.error(f"Failed to initialize Qdrant client: {e}")
            raise

        # 日本語多言語対応のFastEmbedモデルのロード
        # Rosetta環境(x86_64)でのPyTorchインストールの制約を避けるため、ONNXベースのFastEmbedを採用
        self.encoder_model_name = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
        try:
            self.encoder = TextEmbedding(model_name=self.encoder_model_name)
            logger.info(f"FastEmbed '{self.encoder_model_name}' loaded successfully.")
            # MiniLM-L12の次元数は384
            self.vector_size = 384
        except Exception as e:
            logger.error(f"Failed to load FastEmbed model: {e}")
            raise
        
        self._ensure_collection_exists()

    def _ensure_collection_exists(self):
        """コレクションが存在しない場合は作成する"""
        try:
            if not self.client.collection_exists(self.collection_name):
                self.client.create_collection(
                    collection_name=self.collection_name,
                    vectors_config=VectorParams(size=self.vector_size, distance=Distance.COSINE),
                )
                logger.info(f"Created new Qdrant collection: {self.collection_name}")
            else:
                logger.debug(f"Qdrant collection '{self.collection_name}' already exists.")
        except Exception as e:
            logger.error(f"Error ensuring collection exists: {e}")

    def add_event(self, turn: int, event_type: str, content: str, is_private: bool, involved_countries: List[str]):
        """
        データベースに世界のイベントを記録する。
        
        Args:
            turn (int): ターン数
            event_type (str): イベントのカテゴリ ("news", "action_result", "summit", "secret_plan" 等)
            content (str): イベントの自然言語による詳細内容
            is_private (bool): 非公開情報（他国から見えない情報）かどうか
            involved_countries (List[str]): このイベントに直接関与している、または知る権利がある国のリスト
        """
        try:
            # コンテンツのベクトル化 (FastEmbed)
            embeddings = list(self.encoder.embed([content]))
            vector = embeddings[0].tolist()
            
            # ペイロード（メタデータ）の作成
            payload = {
                "turn": turn,
                "event_type": event_type,
                "content": content,
                "is_private": is_private,
                "involved_countries": involved_countries
            }
            
            import uuid
            point_id = str(uuid.uuid4())
            
            self.client.upsert(
                collection_name=self.collection_name,
                points=[
                    PointStruct(
                        id=point_id,
                        vector=vector,
                        payload=payload
                    )
                ]
            )
            logger.debug(f"Event added to DB [Turn {turn}]: {event_type} (Private: {is_private})")
            
        except Exception as e:
            logger.error(f"Failed to add event to DB: {e}")

    def search_events(self, searcher_country: str, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        """
        アクセス制御付きで過去のイベントをセマンティック検索する。

        Args:
            searcher_country (str): 検索を実行する主体の国名（例: "イギリス"）
            query (str): 検索クエリ文字列
            limit (int): 取得する最大件数
            
        Returns:
            List[Dict[str, Any]]: 検索結果のリスト（ペイロード情報のみ）
        """
        try:
            # クエリのベクトル化 (FastEmbed)
            # 汎用モデルのためプレフィックスは無し
            query_embeddings = list(self.encoder.embed([query]))
            query_vector = query_embeddings[0].tolist()
            
            # アクセス制御フィルタの構築
            # 条件: 「公開情報である(is_private=False)」 OR 「検索者が関与国に含まれる」
            access_filter = Filter(
                should=[
                    FieldCondition(
                        key="is_private",
                        match=MatchValue(value=False)
                    ),
                    FieldCondition(
                        key="involved_countries",
                        match=MatchValue(value=searcher_country)
                    )
                ]
            )
            
            search_result = self.client.query_points(
                collection_name=self.collection_name,
                query=query_vector,
                query_filter=access_filter,
                limit=limit
            ).points
            
            results = []
            for hit in search_result:
                results.append(hit.payload)
                
            logger.info(f"[{searcher_country}] DB Search Query: '{query}' -> Found {len(results)} results.")
            return results
            
        except Exception as e:
            logger.error(f"Search failed for {searcher_country}: {e}")
            return []

# 簡易的な動作確認テスト
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    db = DBManager(db_path=":memory:") # テスト用オンメモリ
    
    # テストデータの投入
    db.add_event(1, "news", "フランスとドイツが公開で貿易協定を締結しました", False, ["フランス", "ドイツ"])
    db.add_event(1, "summit", "フランスとイギリスが極秘で軍事同盟の協議を行いました", True, ["フランス", "イギリス"])
    db.add_event(2, "secret", "ロシアがウクライナの主要インフラへのサイバー攻撃を計画しています", True, ["ロシア"])
    
    # アクセス制御のテスト
    print("\n--- イギリスの検索結果 (フランスとの極秘会談は見れるか？) ---")
    results_uk = db.search_events("イギリス", "フランスとの二国間関係や会談履歴")
    for r in results_uk:
        print(f"Turn {r['turn']} [{r['event_type']}]: {r['content']} (Private: {r['is_private']})")
        
    print("\n--- ドイツの検索結果 (フランスとイギリスの極秘会談は見れないはず) ---")
    results_ger = db.search_events("ドイツ", "フランスの軍事的な動きや会談")
    for r in results_ger:
        print(f"Turn {r['turn']} [{r['event_type']}]: {r['content']} (Private: {r['is_private']})")
