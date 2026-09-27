<!-- i18n-source-sha256: 696652d73445aaa9f3fc920f090fdaad3b7dd627a2bba4f5c8530f054a937506 -->
# 데스크톱 GUI 자동화

`local-shell-mcp`는 Linux, Windows, macOS의 네이티브 데스크톱 애플리케이션을 관찰하고 제어할 수 있습니다. 공개 인터페이스는 의도적으로 작게 유지됩니다.

| 도구 | 목적 |
|---|---|
| `gui_list` | 표시 중인 애플리케이션 창을 나열하고 활성 네이티브 백엔드와 기능을 반환합니다. |
| `gui_state` | 하나의 창을 관찰합니다. 짧은 수명의 `state_id`, 접근성 요소, 창 기하 정보, 선택적으로 네이티브 MCP 스크린샷을 반환합니다. |
| `gui_action` | 해당 관찰 결과에 대해 의미 기반 또는 좌표 기반 동작을 실행합니다. |

세 도구 모두 선택적 `machine` 인수를 받으므로 동일한 흐름으로 연결된 데스크톱 worker를 대상으로 할 수 있습니다.

## 관찰한 뒤 동작하기

먼저 `gui_list`를 호출하고 `window_id`를 선택한 다음 `gui_state`를 호출합니다. 대상 컨트롤을 나타내는 접근성 `element_id`가 반환되면 이를 우선 사용하십시오.

```text
gui_list
  -> gui_state(window_id)
  -> gui_action(window_id, state_id, [{type: "click", element_id: "e17"}])
  -> gui_state(window_id)
```

창 상대 `x`/`y` 좌표는 canvas나 사용자 정의 그리기 컨트롤처럼 유용한 접근성 요소가 없는 경우에만 사용하십시오. 반환된 요소 경계와 스크린샷은 HiDPI/Retina 환경을 포함해 동일한 창 상대 논리 픽셀 공간을 사용합니다. 선택된 창 밖의 원시 좌표는 거부됩니다.

`state_id`는 30초 후 만료되며 한 번만 사용할 수 있습니다. 좌표 동작은 관찰 이후 대상 창이 이동하거나 크기가 바뀌지 않았는지도 확인합니다. 어느 검증이든 실패하면 오래된 좌표를 재사용하지 말고 `gui_state`를 다시 호출하십시오.

지원 동작은 `click`, `double_click`, `right_click`, `move`, `scroll`, `drag`, `type`, `key`, `set_value`, `focus`, `wait`입니다.

## Native WebUI에서의 사람 제어

Native WebUI에는 동일한 네이티브 GUI 백엔드를 직접 조작하는 **Desktop** 페이지가 있습니다. 머신과 창을 고른 뒤, 표시된 창 이미지에서 클릭, 더블 클릭, 오른쪽 클릭, 드래그, 휠, 키보드 단축키 또는 IME/CJK 입력용 텍스트 필드를 사용할 수 있습니다.

이 경로는 모델의 `state_id` 의미와 의도적으로 분리되어 있습니다. 표시된 각 프레임은 관찰한 창 기하 정보를 포함하며, 모든 사람 입력 요청은 입력을 주입하기 전에 창의 기하가 정확히 같은지 확인합니다. 창이 이동·크기 변경·사라진 경우 동작을 거부하고 WebUI가 관찰을 새로 고칩니다. 원시 좌표는 계속 선택된 창 내부로 제한됩니다.

키보드와 텍스트 동작은 주입 전에 선택한 네이티브 창에 명시적으로 포커스를 둡니다. WebUI는 VNC/WebRTC 비디오 스트리밍 대신 가벼운 스크린샷 폴링을 사용합니다. 원격 전용 `gui_human_action` RPC는 controller-worker 내부 작업이며 모델에 노출되는 MCP 도구가 아닙니다.

## 네이티브 백엔드

| 플랫폼 | 접근성 / 의미 기반 제어 | 캡처와 원시 입력 |
|---|---|---|
| Windows | Microsoft UI Automation | 창 캡처와 Windows 네이티브 마우스/키보드 입력 |
| macOS | Accessibility (`AXUIElement`) | 선택 창의 `screencapture`와 Quartz `CGEvent` 입력 |
| Linux | AT-SPI | X11 네이티브 입력/캡처, Wayland는 네이티브 데스크톱 캡처와 XDG Desktop Portal RemoteDesktop/ScreenCast 사용 |

가능하면 의미 기반 동작을 먼저 시도합니다. 네이티브 invoke/press 동작을 제공하는 버튼은 픽셀 좌표를 추측하지 않고 활성화할 수 있습니다. 접근성이 없거나 사용자 정의로 그려진 콘텐츠에서는 시각 좌표가 fallback입니다.

## 플랫폼 설정

### Windows

LSM을 제어 대상 애플리케이션과 같은 대화형 데스크톱 세션에서 실행하십시오. 기본 `local-shell-mcp` 설치는 headless 환경에서도 안전하며 Windows UI Automation adapter를 필수로 요구하지 않습니다. 로컬 Windows GUI 제어가 필요할 때만 선택적 `local-shell-mcp[gui]` extra를 설치하십시오.

### macOS

LSM 호스트 프로세스에 다음 권한을 부여하십시오.

- 의미 기반 제어와 입력을 위한 **손쉬운 사용** 권한.
- 스크린샷을 위한 **화면 기록** 권한.

기본 패키지는 PyObjC를 요구하지 않습니다. 로컬 macOS GUI 제어가 필요할 때만 선택적 `local-shell-mcp[gui]` extra를 설치하면 되며, GUI 도구를 사용하지 않는 머신에는 해당 framework가 필요하지 않습니다.

### Linux

데스크톱 세션은 AT-SPI를 노출해야 합니다. Debian/Ubuntu에서는 보통 다음 명령으로 필요한 시스템 binding을 설치할 수 있습니다.

```bash
sudo apt install python3-gi gir1.2-atspi-2.0
```

기본 패키지는 Python X11 또는 D-Bus adapter를 요구하지 않습니다. 선택적 `local-shell-mcp[gui]` extra가 로컬 GUI 사용에 필요한 adapter를 설치합니다. 원격 worker는 GUI 의존성 bootstrap 전에 활성 Linux 세션을 감지합니다. X11은 X11 adapter만, Wayland는 D-Bus adapter만 필요하며 headless worker는 둘 다 설치하지 않습니다. Wayland의 원시 포인터/키보드 fallback은 XDG Desktop Portal RemoteDesktop API를 사용하므로 최초에 권한/세션 선택 창이 표시될 수 있습니다. KDE와 GNOME portal 구현을 지원합니다. 창 스크린샷은 사용 가능한 네이티브 캡처 경로를 사용하고 필요하면 Screenshot portal로 fallback합니다.

LSM worker는 그래픽 로그인 환경 밖에서 시작되는 경우가 많습니다. Linux backend는 직접 상속되지 않은 `DISPLAY`, `WAYLAND_DISPLAY`, `XDG_SESSION_TYPE` 및 관련 변수를 사용자 systemd 환경에서 복구합니다.

## 원격 데스크톱

GUI 도구는 controller가 아니라 선택된 머신에서 실행됩니다. 원격 worker는 대상 데스크톱을 소유한 사용자/세션에 속해야 합니다. GUI adapter는 lazy 방식이며 GUI 호출에만 적용됩니다. 일반 worker 시작과 shell/files/browser 사용에서는 이를 설치하거나 import하지 않습니다. Linux에서는 headless worker가 GUI pip bootstrap 전에 GUI unavailable을 반환하고, 그래픽 worker는 현재 X11/Wayland 세션에 필요한 adapter만 확인하거나 설치합니다.

원격 `gui_state`가 반환하는 스크린샷은 LSM 파일 전송 경로를 통해 전달되고 네이티브 MCP 이미지 콘텐츠로 모델에 노출됩니다. worker JSON 응답에는 포함되지 않습니다.
