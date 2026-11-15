FROM python:3.14-slim
ARG VCS_REF=unknown
LABEL org.opencontainers.image.revision=$VCS_REF
LABEL io.devflow.version-endpoint="1"
WORKDIR /app
COPY app.py .
USER 65532:65532
EXPOSE 8080
CMD ["python3", "-u", "app.py"]
