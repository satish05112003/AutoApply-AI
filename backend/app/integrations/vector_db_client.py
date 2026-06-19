import logging
from typing import List, Dict, Any, Optional
from qdrant_client import QdrantClient
from qdrant_client.http import models
from qdrant_client.http.exceptions import UnexpectedResponse
from app.config import settings

logger = logging.getLogger("autoapply_ai.qdrant")

class QdrantDBClient:
    def __init__(self):
        self.is_available = False
        try:
            if settings.QDRANT_API_KEY:
                self.client = QdrantClient(
                    url=settings.QDRANT_URL,
                    api_key=settings.QDRANT_API_KEY,
                    timeout=3
                )
            else:
                self.client = QdrantClient(url=settings.QDRANT_URL, timeout=3)
            # Quick ping to verify connectivity
            self.client.get_collections()
            self.is_available = True
            logger.info("Qdrant connection established successfully.")
        except Exception as e:
            logger.warning(f"Qdrant unavailable at startup: {e}. Vector search/storage disabled.")
            self.client = None
            
    def init_collection(self, collection_name: str, vector_size: int = 384):
        """Initialize collection if it doesn't already exist."""
        if not self.is_available:
            return
        try:
            # Check if exists
            self.client.get_collection(collection_name=collection_name)
            logger.info(f"Qdrant collection '{collection_name}' already exists.")
        except Exception:
            try:
                # Create it
                logger.info(f"Creating Qdrant collection '{collection_name}' with vector size {vector_size}...")
                self.client.create_collection(
                    collection_name=collection_name,
                    vectors_config=models.VectorParams(
                        size=vector_size,
                        distance=models.Distance.COSINE
                    )
                )
                logger.info(f"Collection '{collection_name}' created successfully.")
            except Exception as ex:
                logger.error(f"Failed to create Qdrant collection '{collection_name}': {ex}")
                raise ex

    def upsert_vector(self, collection_name: str, point_id: str, vector: List[float], payload: Dict[str, Any]):
        """Upsert a single point (vector + metadata payload) to a collection."""
        if not self.is_available:
            return
        try:
            self.init_collection(collection_name, len(vector))
            self.client.upsert(
                collection_name=collection_name,
                points=[
                    models.PointStruct(
                        id=point_id,
                        vector=vector,
                        payload=payload
                    )
                ]
            )
            logger.info(f"Upserted point '{point_id}' into collection '{collection_name}'.")
        except Exception as e:
            logger.error(f"Failed to upsert vector to Qdrant collection '{collection_name}': {e}")

    def upsert_vectors_batch(self, collection_name: str, points_data: List[Dict[str, Any]]):
        """Upsert a list of points (each dict containing: id, vector, payload) in batch."""
        if not self.is_available or not points_data:
            return
        try:
            vector_size = len(points_data[0]["vector"])
            self.init_collection(collection_name, vector_size)
            points = [
                models.PointStruct(
                    id=pd["id"],
                    vector=pd["vector"],
                    payload=pd["payload"]
                )
                for pd in points_data
            ]
            self.client.upsert(
                collection_name=collection_name,
                points=points
            )
            logger.info(f"Upserted {len(points)} points in batch into collection '{collection_name}'.")
        except Exception as e:
            logger.error(f"Failed to upsert batch vectors to Qdrant collection '{collection_name}': {e}")

    def search_similar(
        self, 
        collection_name: str, 
        query_vector: List[float], 
        limit: int = 5,
        filter_payload: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        """Search for similar vectors, returning the scores and payload."""
        if not self.is_available:
            return []
        # Convert simple filter_payload dict to Qdrant Filter models if present
        qdrant_filter = None
        if filter_payload:
            conditions = []
            for key, val in filter_payload.items():
                conditions.append(
                    models.FieldCondition(
                        key=key,
                        match=models.MatchValue(value=val)
                    )
                )
            qdrant_filter = models.Filter(must=conditions)

        try:
            results = self.client.query_points(
                collection_name=collection_name,
                query=query_vector,
                query_filter=qdrant_filter,
                limit=limit
            )
            
            return [
                {
                    "id": hit.id,
                    "score": hit.score,
                    "payload": hit.payload
                }
                for hit in results.points
            ]
        except Exception as e:
            logger.error(f"Failed to query Qdrant similarity: {e}")
            return []

    def delete_point(self, collection_name: str, point_id: str):
        """Delete a single point by its ID."""
        if not self.is_available:
            return
        try:
            self.client.delete(
                collection_name=collection_name,
                points_selector=models.PointIdsList(points=[point_id])
            )
            logger.info(f"Deleted point '{point_id}' from Qdrant collection '{collection_name}'.")
        except Exception as e:
            logger.error(f"Failed to delete point '{point_id}': {e}")

# Global Client Instance
qdrant_client = QdrantDBClient()
