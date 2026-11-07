<!-- i18n-source-sha256: 474398c2065f510156f7fba24967ca8f6600b586ffb1e002416b7a10dc34c3dc -->
# 통합된 웹 작업공간

**통합 LSM 웹 작업공간**은 local-shell-mcp를 일상적으로 사용하는 데 권장되는 방법입니다. 수정된 벤더 LibreChat 프런트엔드를 기반으로 AI 채팅, 프로젝트 기록 및 LSM 제어 평면을 하나의 반응형 인터페이스에 결합합니다. [ChatGPT](chatgpt-connector.md) 또는 [Gemini](gemini-spark.md)와 같은 외부 MCP 클라이언트를 계속 연결할 수 있습니다.

작업 영역은 **자체 호스팅되며 선택적으로 설치됩니다**. 이는 최소 컨트롤러 이미지, 독립 실행형 실행 파일 또는 원격 작업자 번들의 일부가 아닌 별도의 웹 서비스입니다. 컨트롤러 전용 배포는 원래 브라우저 UI 및 OpenTUI를 유지합니다.

## 작업실에는 무엇이 있나요?

| 면적 | 당신이 할 수 있는 일 |
|---|---|
| 채팅 및 프로젝트 | 구성된 모델을 선택하고, 대화를 만들고, 프로젝트를 구성하고, 지난 채팅을 찾고, 대화를 보관하세요. 기록은 서버에 남아있습니다. |
| 컨트롤러 개요 | 상태, 최근 활동 및 연결된 컴퓨터를 봅니다. |
| 파일 | 로컬 또는 원격 파일을 찾아보고 관리합니다. |
| 터미널 | 컨트롤러 또는 작업자의 영구 터미널을 사용하여 작업합니다. |
| 데스크탑 | 원격 GUI 세션을 검사하고 제어합니다. |
| 세션 | 내구성 있는 LSM 작업과 해당 수명 주기를 검사합니다. |
| 리모콘 | 아웃바운드 작업자를 연결하고 관리합니다. |
| 감사 | 모델에서 생성된 도구 활동을 검사합니다. |
| 중첩된 MCP | LSM 뒤에 있는 외부 MCP 서버를 등록, 편집, 활성화, 비활성화, 새로 고침 및 제거합니다. |

컨트롤러 경로는 `/control/overview`, `/control/files`, `/control/terminals`, `/control/desktop`, `/control/sessions`, `/control/remotes` 및 `/control/audit`입니다. 채팅은 `/c/new`에서 열립니다. LSM MCP 관리자는 **LSM의 중첩 MCP 레지스트리**를 제어합니다. LibreChat에서는 두 번째 레지스트리를 생성하지 않습니다.

## 선택적 채팅 스택 배포

1. OAuth가 포함된 [Install and start an LSM Controller](quickstart.md), 적절하게 격리된 작업 공간 및 영구 `file` 또는 `redis` 상태 저장소입니다. Docker Compose를 설치하고 웹 스택을 실행하는 호스트에 저장소를 복제합니다.
2. **동일한 사이트에 두 개의 HTTPS 원본**(예: 컨트롤러용 `https://lsm.example.org` 및 작업공간용 `https://chat.example.org`)을 제공합니다. 채팅 서비스는 신뢰할 수 없는 네트워크에 직접 노출되지 않습니다.
3. `openssl rand -hex 32`를 사용하여 하나의 브리지 비밀을 생성합니다. 해당 보안 비밀을 사용하여 **컨트롤러 서비스**에서 다음 환경 변수를 구성한 후 다시 시작하세요.

```env
LOCAL_SHELL_MCP_LIBRECHAT_URL=https://chat.example.org
LOCAL_SHELL_MCP_LIBRECHAT_BRIDGE_SECRET=paste-the-same-64-hex-character-secret-on-both-services
```

4. 리포지토리 체크아웃에서 선택적 웹 스택을 구성합니다. 개인 환경 파일을 사용하거나 아래 표시된 값을 내보내십시오. 고유하고 강력한 비밀을 생성하고 커밋하지 마세요.

```sh
export LSM_PUBLIC_ORIGIN=https://lsm.example.org
export LIBRECHAT_PUBLIC_URL=https://chat.example.org
export LSM_LIBRECHAT_BRIDGE_SECRET="paste-the-secret-from-controller-config"
export JWT_SECRET="$(openssl rand -hex 32)"
export JWT_REFRESH_SECRET="$(openssl rand -hex 32)"
export CREDS_KEY="$(openssl rand -hex 32)"
export CREDS_IV="$(openssl rand -hex 16)"
export MEILI_MASTER_KEY="$(openssl rand -hex 32)"
export LSM_DOCKER_NETWORK=local-shell-mcp_default
```

5. 비공개 구성을 렌더링한 다음 별도로 배포된 채팅 스택을 빌드하고 시작합니다.

```sh
python3 integrations/librechat/render_config.py
docker compose -f integrations/librechat/compose.yaml build chat
docker compose -f integrations/librechat/compose.yaml up -d
```

루트 Docker Compose 배포를 사용하는 경우 위의 컨트롤러 변수는 루트 `.env`에 속하며 컨테이너로 전달됩니다. 채팅 서비스 값은 셸 내보내기 또는 개인 환경 파일을 통해 제공될 수 있습니다. 컨트롤러 컨테이너는 명명된 Docker 네트워크의 `http://local-shell-mcp:8765`에 있는 채팅 컨테이너에서 연결할 수 있어야 합니다. 채팅 HTTPS 원본에 대한 역방향 프록시 포트 `127.0.0.1:3080`, 외부 호스트를 보존하고 저장소에서 [deployment and security notes](https://github.com/fwerkor/local-shell-mcp/blob/main/integrations/librechat/README.md)를 따릅니다. 웹 스택은 Node.js, MongoDB, Meilisearch 및 SearXNG를 실행합니다. 이들은 작업자에 포함되지 **않습니다**. 이 별도의 배포는 저장소 루트의 일반 `docker compose up -d`로 시작되지 않습니다.

## 로그인하고 채팅을 사용하세요

1. `https://lsm.example.org/ui`를 열고 **LSM 컨트롤러** 로그인을 사용하여 인증한 후 일회성 핸드오프를 따라 웹 작업 공간으로 이동합니다. 두 번째 LibreChat 사용자 계정을 생성하지 않습니다.
2. 채팅 서비스에 사용 가능한 LLM 공급자 또는 모델 엔드포인트를 구성합니다. 작업공간은 채팅 인터페이스와 도구 브리지를 제공합니다. **모델이나 API 크레딧은 포함되지 않습니다**.
3. 대화를 만드세요. 웹 검색 및 LSM 도구는 컨트롤러 권한에 따라 기본적으로 활성화됩니다. 필요에 따라 대화별 **웹**, **LSM**, **외부 MCP** 및 **메모리** 컨트롤을 사용합니다.
4. 읽기 전용 요청으로 시작하세요: "컨트롤러 상태를 확인하고 작업공간 루트를 나열하세요. 파일을 수정하지 마세요."
5. **파일**, **터미널**, **데스크톱**, **세션**, **원격** 또는 **감사**로 이동하여 직접 검사하고 제어하세요.

채팅 업로드(최대 32MiB)는 컨트롤러 작업 영역에 저장되며 절대 경로가 모델에 제공됩니다. 브라우저 업로드는 추가 파일 권한을 부여하지 않습니다. 모델 지향 도구 호출은 LSM 인증, 감사 및 원격 작업자 라우터를 통과합니다.

## 외부 MCP, 보안 및 데이터

작업공간 MCP 사이드바를 사용하여 중첩된 외부 MCP 서버를 관리하세요. 이는 별도의 개인 환경 변수 및 요청 헤더를 포함하여 로컬 stdio 서버 및 HTTP 서버를 지원합니다. 비밀은 브라우저에 반환되지 않습니다. **외부 MCP** 채팅 토글을 사용하면 중첩된 도구를 검색, 검사 및 호출할 수 있습니다. 기본 LSM 도구가 비활성화된 경우 모델 `mcp_manage`를 부여하지 않습니다. UI 관리는 일반 컨트롤러 인증으로 보호됩니다.

채팅 메시지, 프로젝트 및 아카이브는 웹 스택의 MongoDB에 서버측에 저장됩니다. 검색은 Meilisearch를 사용합니다. 컨트롤러는 도구 권한, 작업자 ID, 세션 상태 및 감사를 별도로 소유합니다. 모든 기록을 유지해야 하는 경우 두 데이터 저장소를 모두 백업하세요. 채팅 백엔드는 LSM 로그인 하의 단일 사용자입니다. 내부 API나 데이터베이스를 대중에게 노출하지 마십시오.

UI는 **iframe이 아닌** 최상위 앱입니다. 선택적 채팅 서비스가 구성되지 않은 경우 `/ui`는 원래 LSM WebUI를 계속 제공합니다. 기본 OpenTUI 및 외부 클라이언트는 계속 지원됩니다.

## 문제 해결

- **리디렉션은 원래 UI에 남아 있습니다.** 영구 컨트롤러 상태 백엔드인 `LOCAL_SHELL_MCP_LIBRECHAT_URL`와 웹 스택의 HTTPS 역방향 프록시를 확인하세요.
- **로그인 또는 핸드오프 실패:** 동일한 사이트 원본, HTTPS 및 서버 시계와 일치하여 양쪽에서 정확히 동일한 32바이트 이상의 브리지 비밀을 확인합니다.
- **채팅이 로드되지만 응답할 수 없음:** 실제 모델 엔드포인트 또는 API 자격 증명을 설정하고 채팅 컨테이너 로그를 확인하세요.
- **MCP 도구가 없습니다.** 컨트롤러 범위 및 대화별 토글을 확인합니다. 중첩된 서버 레지스트리는 LibreChat MCP 데이터베이스와 별개입니다.
- **파일 또는 세션이 비어 있는 것으로 나타남:** 채팅이 올바른 컨트롤러 및 작업 영역에 도달하는지 확인하고 API 인증 로그를 검사합니다.

구현 세부정보 및 업데이트는 [the vendored integration README](https://github.com/fwerkor/local-shell-mcp/blob/main/integrations/librechat/README.md) 및 [human interface guide](../guides/human-interface.md)를 참조하세요.
