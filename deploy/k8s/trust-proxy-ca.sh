#!/usr/bin/env bash
# kind 노드에 "TLS 가로채기 프록시"의 CA를 신뢰시킨다.
#
# 왜 필요한가:
#   기업 네트워크가 TLS를 가로채면(프록시가 연결을 끊고 자체 CA로 재서명) 노드 안
#   containerd가 레지스트리 인증서를 검증하지 못하고 이미지 pull이 전부 실패한다.
#
#     failed to do request: Head "https://registry.k8s.io/v2/...":
#     tls: failed to verify certificate: x509: certificate signed by unknown authority
#
#   macOS 키체인에는 그 CA가 설치돼 있어서 **호스트 docker pull은 멀쩡하다**. 그래서
#   "도커는 되는데 클러스터만 안 되는" 형태로 나타나고 원인을 찾기 어렵다.
#
# 왜 인증서를 리포지토리에 커밋하지 않는가:
#   CA는 네트워크마다 다르다. 커밋해두면 다른 망에서는 틀린 값이 되고, 사무실 밖에서
#   클론한 사람에게는 정체불명의 인증서를 심는 스크립트가 된다. 실제 연결에서 그때그때
#   뽑는 편이 정확하다.
#
# 가로채기가 없는 망에서는:
#   체인에 공개 CA만 들어 있고, 노드는 이미 그것을 신뢰한다. 설치해도 무해하므로
#   분기하지 않는다.
set -euo pipefail

cluster="${1:?사용법: trust-proxy-ca.sh <kind-cluster-name>}"
probe="${2:-registry.k8s.io:443}"

# leaf(체인의 첫 인증서)는 서버 인증서라 CA 저장소에 넣을 대상이 아니다. 두 번째
# 블록부터가 중간/루트 CA다.
intermediates="$(
  openssl s_client -connect "$probe" -showcerts </dev/null 2>/dev/null |
    awk '/-----BEGIN CERTIFICATE-----/{n++; if (n > 1) inside = 1}
         inside {print}
         /-----END CERTIFICATE-----/{inside = 0}'
)"

if [ -z "$intermediates" ]; then
  echo "[trust-proxy-ca] $probe 체인에 중간 CA가 없다. 건너뛴다."
  exit 0
fi

issuer="$(printf '%s' "$intermediates" | openssl x509 -noout -subject 2>/dev/null || echo '알 수 없음')"
echo "[trust-proxy-ca] 발급자: $issuer"

for node in $(kind get nodes --name "$cluster"); do
  printf '%s\n' "$intermediates" |
    docker exec -i "$node" tee /usr/local/share/ca-certificates/proxy-intercept.crt >/dev/null
  docker exec "$node" update-ca-certificates >/dev/null
  # containerd는 시작할 때 CA 저장소를 읽는다. 재시작하지 않으면 갱신이 반영되지 않는다.
  docker exec "$node" systemctl restart containerd
  echo "[trust-proxy-ca] $node 적용 완료"
done
