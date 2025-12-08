FROM mambaorg/micromamba:0.24.0

# recommended by mambaorg docs for Dockerfiles
ARG MAMBA_DOCKERFILE_ACTIVATE=1

# Basic system tools
USER root
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
      git wget curl ca-certificates unzip && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Create an sbas user (do i really need this?)
RUN useradd -m -s /bin/bash sbas

# Switch to sbas and copy code with correct ownership
# USER sbas
WORKDIR /home/sbas
COPY --chown=sbas:sbas . /home/sbas

# Install Python + ISCE2 + MintPy + service deps in the "base" env
ARG PYTHON_VERSION="3.10"
RUN micromamba install -y -n base -c conda-forge \
      python=${PYTHON_VERSION} \
      isce2 \
      mintpy \
      gdal \
      proj \
      proj-data \
      rasterio \
      "pystac>=1.8" \
      pip && \
    micromamba run -n base python -m pip install --no-cache-dir -r requirements.txt && \
    micromamba clean --all --yes

ENV PROJ_LIB=/opt/conda/share/proj \
    PROJ_DATA=/opt/conda/share/proj \
    GDAL_DATA=/opt/conda/share/gdal

# Make sure dem.py (one of the steps*.py uses it) is on PATH
RUN ln -s /opt/conda/lib/python${PYTHON_VERSION}/site-packages/isce/applications/dem.py \
          /opt/conda/bin/dem.py

# Download auxiliary calibration files
RUN mkdir -p /home/sbas/aux_cal && \
    cd /home/sbas/aux_cal && \
    wget https://sar-mpc.eu/download/ca97845e-1314-4817-91d8-f39afbeff74d/ -O aux_cal.zip && \
    unzip aux_cal.zip && \
    rm aux_cal.zip

# Working dir for data
WORKDIR /work

# Make base env Python the default at runtime
# This will allow, e.g.
# python run_pipeline.py ...
# to be interpreted as:
# micromamba run -n base python run_pipeline.py ...
#
ENV CONDA_PREFIX=/opt/conda/envs/base
ENV PATH=${CONDA_PREFIX}/bin:/opt/conda/bin:${PATH}

# Make app importable (optional but handy)
ENV PYTHONPATH=/home/sbas

# Run SBAS.py inside the "base" env
# ENTRYPOINT ["micromamba", "run", "-n", "base", "python", "/home/sbas/SBAS.py"]
# CMD ["--config", "/home/sbas/configs/config.yaml"]
ENTRYPOINT ["micromamba", "run", "-n", "base"]
