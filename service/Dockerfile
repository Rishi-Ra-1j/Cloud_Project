FROM python:3.11-slim
WORKDIR /app
# torch CPU wheel is large; install it from the CPU index, no cache, so the
# image stays <= 2 GB and carries no model weights.
COPY requirements.txt .
RUN pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu \
      torch==2.15.0+cpu && \
    pip install --no-cache-dir -r requirements.txt
COPY app.py schema.json ./
EXPOSE 8000
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
