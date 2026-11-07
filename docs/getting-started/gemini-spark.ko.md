<!-- i18n-source-sha256: b7c3dfd7dc21a498f8410a88a8a52094ca0349856dfa43d267e3fe7bb273685a -->
# Gemini Spark/맞춤형 앱 연결

Gemini의 **사용자 정의 연결된 앱** 기능(이전의 **Spark**)을 사용하면 자격을 갖춘 Gemini 사용자가 원격 MCP 서버에 연결할 수 있습니다. LSM은 MCP 끝점을 제공할 수 있습니다. 이는 [unified web workspace](web-workspace.md), [ChatGPT](chatgpt-connector.md) 및 기타 MCP 클라이언트에 대한 **대체 클라이언트 연결**입니다. LSM 컨트롤러를 교체하거나 배포하지 않습니다.

Google은 현재 맞춤 앱을 **개인 Google 계정**으로 로그인하고 **활동 유지를 활성화**한 **미국의 18세 이상 사용자**로 제한하고 있습니다. 이 기능은 **영어**로 제공됩니다. 연결된 앱은 나중에 모바일에서 사용할 수 있지만 연결은 Gemini 웹 앱에서 생성되어야 합니다. 가용성 및 UI 라벨은 변경될 수 있습니다. [official Gemini custom apps instructions](https://support.google.com/gemini/answer/17209137)를 참조하세요.

## 연결하기 전에

- 예를 들어 [Docker Compose](../installation/docker.md)를 사용하여 LSM 런타임을 시작하고 상태를 확인합니다.
- **공개적으로 연결 가능한 HTTPS**를 통해 MCP 엔드포인트를 노출하고 OAuth를 활성화된 상태로 유지하세요.
- 컨트롤러의 인증 세부정보를 파악하고 필요한 범위만 승인하세요.
- 제한된 작업 공간이나 컨테이너를 사용하세요. Gemini는 파일, 기계 및 터미널에 실제 영향을 미치는 작업을 요청할 수 있습니다.

Gemini에 진입할 엔드포인트는 다음과 같습니다.

```text
https://your-public-host.example.com/mcp
```

웹 UI(`/ui`), LibreChat URL 또는 `/mcp` 없이 사이트 출처를 입력하지 마세요. 공개 배포에서는 연결 오류를 해결하기 위해 인증을 비활성화해서는 안 됩니다.

## 쌍둥이 자리에 연결

1. 컴퓨터에서 [Gemini](https://gemini.google.com/)를 열고 적합한 개인 계정으로 로그인하세요.
2. **설정 및 도움말 → 연결된 앱**을 엽니다. 현재 인터페이스에 따라 **개인 정보 → 연결된 앱** 아래에 있을 수 있습니다.
3. **맞춤 앱**에서 **맞춤 앱 추가**를 선택하거나 맞춤 앱 URL 필드를 사용하세요.
4. LSM HTTPS `/mcp` URL을 붙여넣은 후 **다음**을 선택합니다.
5. LSM 컨트롤러를 사용하여 OAuth 및 동의 흐름을 완료합니다. LSM은 OAuth 검색 및 동적 클라이언트 등록을 지원합니다. Gemini가 대신 수동 OAuth 클라이언트 자격 증명을 요청하는 경우 계속하기 전에 고급 옵션과 LSM OAuth 설정을 확인하세요.
6. Gemini 대화에서 `@`를 입력하고 연결된 맞춤형 앱을 선택하여 LSM 도구를 요청하세요.

"연결된 LSM 앱을 사용하여 환경을 검사하고 작업 공간 파일을 나열합니다. 아무것도 수정하지 마세요."로 시작하세요. 쓰기 작업을 시도하기 전에 도구 결과와 컨트롤러 감사를 확인하세요.

## 제한 사항 및 문제 해결

- **맞춤형 앱 옵션 없음:** 계정, 지역, 연령, 언어 및 Keep Activity 자격을 확인하세요. 이는 LSM 구성 오류가 아닌 Gemini 측 가용성 제한입니다.
- **URL이 거부되었습니다.** 외부에서 연결할 수 있는 HTTPS `/mcp` 엔드포인트를 사용하세요. OAuth 검색 및 역방향 프록시를 확인하세요.
- **OAuth 실패:** LSM 인증 화면, 클라이언트 등록, 콜백 URL 및 부여된 범위를 확인하세요. 인증되지 않은 MCP 엔드포인트를 게시하지 마십시오.
- **도구가 없거나 실패함:** 클라이언트 측 MCP 도구/스키마 지원은 다를 수 있습니다. 간단한 읽기 전용 호출을 시도하고 LSM 감사 및 로그를 검사하십시오. 모든 Gemini 클라이언트 기능과의 완전한 호환성은 보장되지 않습니다.
- **연결 해제 중:** 더 이상 필요하지 않은 LSM을 비활성화, 연결 해제 또는 제거하려면 **연결된 앱**으로 돌아가세요.

Google의 [official guide](https://support.google.com/gemini/answer/17209137)에서는 최신 맞춤 앱 흐름과 가용성을 설명합니다. 대신 로컬 CLI 기반 Gemini 통합의 경우 [Gemini CLI's MCP documentation](https://geminicli.com/docs/tools/mcp-server/)를 참조하세요. LSM [ChatGPT connector tutorial](chatgpt-connector.md)는 독립적으로 계속 사용할 수 있습니다.
