ARG BASE_IMAGE=open-cinema-ci-base
FROM ${BASE_IMAGE}

USER root
COPY --chown=opencinema:opencinema open-cinema/ /workspace/
COPY --chown=opencinema:opencinema wyreplumber/ /wyreplumber/
COPY --chown=opencinema:opencinema pcm-auto-decoder/ /pcm-auto-decoder/
USER opencinema
WORKDIR /workspace
