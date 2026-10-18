# GitHub에서 매일 아침 자동 실행하기

## 1단계. 해외 서버에서 은행 사이트가 열리는지 먼저 시험 (구글 설정 전)

1. github.com 로그인 → 오른쪽 위 **+** → **New repository**
   - Repository name: `rate-bot` / **Private** 선택 → **Create repository**
2. 새 저장소 화면에서 **uploading an existing file** 클릭 → 아래 파일을 끌어다 놓고 **Commit changes**
   - `scraper.py`, `config.json`, `README.md`
3. `.github/workflows/daily.yml`은 폴더째로 올려야 합니다. 저장소에서 **Add file → Create new file** →
   파일 이름 칸에 `.github/workflows/daily.yml` 을 그대로 입력 → daily.yml 내용을 붙여 넣고 **Commit changes**
4. 저장소 위쪽 **Actions** 탭 → 왼쪽 **daily-rate-scrape** → **Run workflow** (dry_run 체크된 상태) → 초록 버튼
5. 1~2분 뒤 실행 기록을 눌러 **금리 수집·기입** 단계를 펼치면 은행별 결과가 나옵니다.
   - 기자님 PC 결과와 같으면 2단계로 진행
   - `None`이나 "페이지 열기 실패"가 나오면 해외 접속 차단입니다. 그 화면을 캡처해 보내 주세요(PC 실행으로 전환).

## 2단계. 봇이 시트에 쓸 수 있게 구글 서비스 계정 만들기

1. console.cloud.google.com 접속(회사 구글 계정 아니어도 됨) → 위쪽 프로젝트 선택 → **새 프로젝트** → 이름 `rate-bot` → 만들기
2. 위 검색창에 **Google Sheets API** → **사용** 클릭
3. 왼쪽 메뉴 **IAM 및 관리자 → 서비스 계정** → **서비스 계정 만들기** → 이름 `rate-bot` → **완료**
4. 만든 서비스 계정 클릭 → **키** 탭 → **키 추가 → 새 키 만들기 → JSON** → 파일이 내려받아집니다(외부 유출 주의)
5. 서비스 계정 이메일(`rate-bot@....iam.gserviceaccount.com`)을 복사 →
   금리 시트 오른쪽 위 **공유** → 그 이메일을 **편집자**로 추가 (팀 공용 시트이니 데스크와 상의 권장)

## 3단계. 키를 GitHub에 등록하고 실제 기입

1. GitHub 저장소 **Settings → Secrets and variables → Actions → New repository secret**
   - Name: `GOOGLE_SERVICE_ACCOUNT_JSON`
   - Secret: 내려받은 JSON 파일을 메모장으로 열어 **전체 내용** 붙여 넣기 → **Add secret**
2. **Actions → daily-rate-scrape → Run workflow** 에서 **dry_run 체크를 끄고** 실행
3. 시트의 오늘 날짜 행에 값이 들어갔는지 확인. 이후로는 평일 오전 8시 30분에 자동 실행됩니다.
   (GitHub 예약 실행은 몇 분~수십 분 늦게 시작될 수 있습니다.)
