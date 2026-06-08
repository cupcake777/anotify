FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY server.py .

ENV ANOTIFY_PUBLIC=1
ENV PORT=7860

EXPOSE 7860
CMD ["python", "server.py", "--host", "0.0.0.0", "--port", "7860", "--public"]
