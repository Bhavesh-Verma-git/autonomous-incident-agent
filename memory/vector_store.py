import os
import chromadb
from chromadb.utils import embedding_functions
import config
from typing import Dict, Any

class IncidentMemory:
    """
    Manages long-term semantic memory of past incidents using raw ChromaDB.
    """
    def __init__(self, persist_directory: str = None, collection_name: str = None):
        self.persist_dir = persist_directory or config.CHROMA_PERSIST_DIR
        self.collection_name = collection_name or config.CHROMA_COLLECTION_NAME
        
        os.makedirs(self.persist_dir, exist_ok=True)
        
        # 1. Initialize the Chroma vector store
        self.client = chromadb.PersistentClient(path=self.persist_dir)
        
        # We use the default embedding function (sentence-transformers/all-MiniLM-L6-v2)
        # which runs completely locally without needing an API key.
        self.emb_fn = embedding_functions.DefaultEmbeddingFunction()
        
        self.collection = self.client.get_or_create_collection(
            name=self.collection_name,
            embedding_function=self.emb_fn
        )

    def store_incident(self, incident_id: str, root_cause: str, resolution: str = "", service: str = "", **kwargs):
        """
        Stores a resolved incident in the vector database.
        """
        summary = kwargs.get("summary", "")
        human_input = kwargs.get("human_input", "")
        
        # Combine the key information into a single text document for embedding
        content = f"Service: {service}\nRoot Cause: {root_cause}\nResolution: {resolution}"
        if summary:
            content = f"Incident: {summary}\n" + content
            
        confidence_score = kwargs.get("confidence_score")
        if confidence_score is not None:
            content += f"\nConfidence Score: {confidence_score:.2f}"
            
        if human_input:
            content += f"\nHuman Assistance Required: Yes\nHuman Insight: {human_input}"
        else:
            content += "\nHuman Assistance Required: No"
            
        past_similar = kwargs.get("past_similar_incidents", [])
        if past_similar:
            content += "\n\nSimilar Past Incidents Consulted:\n" + "\n".join(past_similar)

            
        # Store in ChromaDB
        self.collection.add(
            documents=[content],
            metadatas=[{"incident_id": incident_id, "service": service}],
            ids=[incident_id]
        )
        print(f"  [Memory] Stored incident {incident_id} in vector DB.")

    def find_similar_incidents(self, current_alert_description: str, n: int = 2) -> Dict[str, Any]:
        """
        Performs a semantic search to find past incidents conceptually similar 
        to the current alert description.
        Returns raw ChromaDB query format.
        """
        if self.collection.count() == 0:
            return {"ids": [[]], "documents": [[]], "distances": [[]]}
            
        try:
            # We use query to get top n matches
            results = self.collection.query(
                query_texts=[current_alert_description],
                n_results=min(n, self.collection.count()),
                include=["documents", "distances", "metadatas"]
            )
            
            # Only return results that are actually similar.
            # Cosine distance < 0.5 means meaningfully related for this embedding model.
            # (Distance range is 0–2; 1.0 would pass everything through — too permissive.)
            SIMILARITY_THRESHOLD = 0.5
            
            good_ids, good_docs = [], []
            for i, distance in enumerate(results["distances"][0]):
                if distance < SIMILARITY_THRESHOLD:
                    good_ids.append(results["ids"][0][i])
                    good_docs.append(results["documents"][0][i])
            
            return {"ids": [good_ids], "documents": [good_docs]}
        except Exception as e:
            print(f"  [Memory] Search failed: {e}")
            return {"ids": [[]], "documents": [[]], "distances": [[]]}
