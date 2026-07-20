# RFVisualizer 중간보고서

`RFVisualizer_interim_report.tex`은 `LaTeX_Template/`의 `pnureport` 형식을 사용한 제출용 원고다.

## 구성

- `RFVisualizer_interim_report.tex`: 본문
- `references.bib`: 참고문헌
- `pnureport.cls`, `pnulogo.jpg`: 원본 템플릿에서 복사한 양식 파일
- `figures/`: 2026년 7월 15일 중간 보고 자료에서 선별한 그림

## 컴파일

템플릿 지침에 따라 pdfLaTeX과 BibTeX을 사용한다.

```bash
pdflatex RFVisualizer_interim_report.tex
bibtex RFVisualizer_interim_report
pdflatex RFVisualizer_interim_report.tex
pdflatex RFVisualizer_interim_report.tex
```

보고 기준은 2026년 7월 15일 회의 자료와 7월 14일 기준 세 저장소의 구현 상태다. 그래픽스의 임시 배율/재질, 임베디드 다중 실물 시험, Viewer/LCD 미구현 범위는 확정 결과와 분리해 서술했다.
