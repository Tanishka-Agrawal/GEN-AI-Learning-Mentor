import os
import json
import numpy as np
from pypdf import PdfReader

# Load API key configuration
import google.generativeai as genai
from dotenv import load_dotenv

load_dotenv()

# Configure Gemini
api_key = os.getenv("GEMINI_API_KEY")
if api_key and not api_key.startswith("your_") and api_key.strip():
    genai.configure(api_key=api_key)
else:
    api_key = None

# Fallback vector index using Numpy
class SimpleVectorIndex:
    def __init__(self):
        self.embeddings = []
        self.chunks = []

    def add_items(self, new_embeddings, new_chunks):
        """new_embeddings: list of list of floats, new_chunks: list of dicts"""
        if not new_embeddings:
            return
        if len(self.embeddings) == 0:
            self.embeddings = np.array(new_embeddings, dtype=np.float32)
        else:
            self.embeddings = np.vstack([self.embeddings, np.array(new_embeddings, dtype=np.float32)])
        self.chunks.extend(new_chunks)

    def search(self, query_embedding, k=4):
        """Perform cosine similarity search and return top-k chunks with scores."""
        if len(self.embeddings) == 0:
            return []
        
        q_emb = np.array(query_embedding, dtype=np.float32)
        
        # Calculate cosine similarity
        # Cosine similarity = (A . B) / (||A|| * ||B||)
        norm_embeddings = np.linalg.norm(self.embeddings, axis=1)
        norm_query = np.linalg.norm(q_emb)
        
        if norm_query == 0:
            return []
            
        dot_product = np.dot(self.embeddings, q_emb)
        # Prevent divide by zero
        norm_product = norm_embeddings * norm_query
        norm_product[norm_product == 0] = 1e-8
        
        similarities = dot_product / norm_product
        
        # Get top-k indices
        top_indices = np.argsort(similarities)[::-1][:k]
        
        results = []
        for idx in top_indices:
            results.append({
                "chunk": self.chunks[idx],
                "score": float(similarities[idx])
            })
        return results

    def save(self, directory):
        os.makedirs(directory, exist_ok=True)
        if len(self.embeddings) > 0:
            np.save(os.path.join(directory, "embeddings.npy"), self.embeddings)
        with open(os.path.join(directory, "chunks.json"), "w", encoding="utf-8") as f:
            json.dump(self.chunks, f, ensure_ascii=False, indent=2)

    def load(self, directory):
        emb_path = os.path.join(directory, "embeddings.npy")
        chunks_path = os.path.join(directory, "chunks.json")
        
        if os.path.exists(chunks_path):
            with open(chunks_path, "r", encoding="utf-8") as f:
                self.chunks = json.load(f)
        else:
            self.chunks = []
            
        if os.path.exists(emb_path):
            self.embeddings = np.load(emb_path)
        else:
            self.embeddings = np.array([], dtype=np.float32)

def extract_text_from_pdf(file_path):
    """Extract text from a PDF file using pypdf."""
    text = ""
    try:
        reader = PdfReader(file_path)
        for page in reader.pages:
            page_text = page.extract_text()
            if page_text:
                text += page_text + "\n"
    except Exception as e:
        print(f"Error reading PDF {file_path}: {e}")
    return text

def chunk_text(text, chunk_size=1000, chunk_overlap=150):
    """Splits text into chunks using recursive splitting on paragraph/sentences."""
    if not text:
        return []
        
    paragraphs = text.split("\n\n")
    chunks = []
    current_chunk = ""
    
    for paragraph in paragraphs:
        paragraph = paragraph.strip()
        if not paragraph:
            continue
            
        if len(current_chunk) + len(paragraph) <= chunk_size:
            current_chunk += paragraph + "\n\n"
        else:
            if current_chunk:
                chunks.append(current_chunk.strip())
            
            # If a single paragraph is too large, split it by sentences
            if len(paragraph) > chunk_size:
                sentences = paragraph.split(". ")
                sub_chunk = ""
                for sentence in sentences:
                    sentence = sentence.strip()
                    if not sentence:
                        continue
                    if len(sub_chunk) + len(sentence) <= chunk_size:
                        sub_chunk += sentence + ". "
                    else:
                        if sub_chunk:
                            chunks.append(sub_chunk.strip())
                        sub_chunk = sentence + ". "
                if sub_chunk:
                    current_chunk = sub_chunk
            else:
                current_chunk = paragraph + "\n\n"
                
    if current_chunk:
        chunks.append(current_chunk.strip())
        
    # Standard overlap adjustment (simplistic representation)
    refined_chunks = []
    for i, c in enumerate(chunks):
        if i == 0:
            refined_chunks.append(c)
        else:
            # Add a bit of the previous chunk text as overlap prefix
            overlap_prefix = chunks[i-1][-chunk_overlap:] if len(chunks[i-1]) > chunk_overlap else chunks[i-1]
            refined_chunks.append(overlap_prefix + " ... " + c)
            
    return refined_chunks

def get_embedding(text):
    """Retrieve embedding vector from Gemini embedding API."""
    if not api_key:
        # Return mock embedding if no key is configured (for baseline operation)
        return [0.0] * 768
        
    try:
        result = genai.embed_content(
            model="models/text-embedding-004",
            content=text,
            task_type="retrieval_document"
        )
        return result['embedding']
    except Exception as e:
        print(f"Error fetching embedding from Gemini: {e}")
        # Try fallback model
        try:
            result = genai.embed_content(
                model="models/embedding-001",
                content=text,
                task_type="retrieval_document"
            )
            return result['embedding']
        except Exception as e2:
            print(f"Fallback embedding model failed: {e2}")
            return [0.0] * 768

def index_file(user_id, file_path, filename):
    """Processes a file, extracts its text, embeds the chunks, and indexes them."""
    # 1. Determine file type and extract text
    _, ext = os.path.splitext(filename.lower())
    if ext == '.pdf':
        text = extract_text_from_pdf(file_path)
    else:
        # Default to plain text
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                text = f.read()
        except Exception as e:
            print(f"Error reading file {filename}: {e}")
            text = ""

    if not text.strip():
        return 0

    # 2. Chunk text
    chunks = chunk_text(text)
    if not chunks:
        return 0

    # 3. Embed chunks
    embeddings = []
    chunk_objects = []
    for i, chunk_text_content in enumerate(chunks):
        emb = get_embedding(chunk_text_content)
        embeddings.append(emb)
        chunk_objects.append({
            "text": chunk_text_content,
            "filename": filename,
            "chunk_id": i
        })

    # 4. Load existing index for user and append new items
    vector_dir = os.path.join(os.path.dirname(__file__), 'instance', 'vectors', str(user_id))
    index = SimpleVectorIndex()
    index.load(vector_dir)
    index.add_items(embeddings, chunk_objects)
    index.save(vector_dir)

    return len(chunks)

def query_user_vector_store(user_id, query_text, k=4):
    """Searches user vector store for the query text. Returns list of chunk dicts."""
    vector_dir = os.path.join(os.path.dirname(__file__), 'instance', 'vectors', str(user_id))
    if not os.path.exists(vector_dir):
        return []
        
    index = SimpleVectorIndex()
    index.load(vector_dir)
    
    query_emb = get_embedding(query_text)
    results = index.search(query_emb, k=k)
    return results

def delete_user_vector_store(user_id):
    """Deletes all vector files for a specific user (e.g. on account reset)."""
    vector_dir = os.path.join(os.path.dirname(__file__), 'instance', 'vectors', str(user_id))
    if os.path.exists(vector_dir):
        for f in os.listdir(vector_dir):
            os.remove(os.path.join(vector_dir, f))
        os.rmdir(vector_dir)

def delete_file_from_vector_store(user_id, filename):
    """Removes chunks belonging to a specific file from user vector store and rebuilds it."""
    vector_dir = os.path.join(os.path.dirname(__file__), 'instance', 'vectors', str(user_id))
    if not os.path.exists(vector_dir):
        return
        
    index = SimpleVectorIndex()
    index.load(vector_dir)
    
    # Filter out chunks matching filename
    keep_indices = [i for i, chunk in enumerate(index.chunks) if chunk['filename'] != filename]
    
    if len(keep_indices) == 0:
        delete_user_vector_store(user_id)
        return
        
    filtered_embeddings = index.embeddings[keep_indices]
    filtered_chunks = [index.chunks[i] for i in keep_indices]
    
    # Re-save index
    index.embeddings = filtered_embeddings
    index.chunks = filtered_chunks
    index.save(vector_dir)
