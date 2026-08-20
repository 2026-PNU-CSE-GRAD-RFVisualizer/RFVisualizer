#!/usr/bin/env bash
# fwd 모델을 기준으로 bwd를 합쳐 하나의 재구성을 만든다.
# 사용법: bash scripts/run_merge.sh
set -e

PGSR=/data/RFVisualizer_Workspace/RFVisualizer/PGSR
SCENE=$PGSR/data/pnu/3f_corridor
cd $PGSR

echo "### 1/5 feature 추출 (1700장, 몇 분)"
rm -rf $SCENE/merge && mkdir -p $SCENE/merge
colmap feature_extractor \
  --database_path $SCENE/merge/database.db \
  --image_path $SCENE/input \
  --ImageReader.single_camera 1 --ImageReader.camera_model OPENCV \
  --SiftExtraction.use_gpu 1

echo "### 2/5 영상 내부 순차 매칭"
colmap sequential_matcher \
  --database_path $SCENE/merge/database.db \
  --SiftMatching.use_gpu 1 --SiftMatching.max_num_matches 32768 \
  --SequentialMatching.overlap 15

echo "### 3/5 fwd-bwd 크로스 쌍 생성"
python scripts/make_cross_pairs.py \
  $SCENE/fwd_seq/merged_ba \
  $SCENE/merge/cross_pairs.txt \
  --bwd-dir $SCENE/input

echo "### 4/5 크로스 매칭 (오래 걸림)"
colmap matches_importer \
  --database_path $SCENE/merge/database.db \
  --match_list_path $SCENE/merge/cross_pairs.txt \
  --match_type pairs \
  --SiftMatching.use_gpu 1 --SiftMatching.max_num_matches 32768

echo "### 5/5 재구성 (제일 오래 걸림)"
mkdir -p $SCENE/merge/sparse
colmap mapper \
  --database_path $SCENE/merge/database.db \
  --image_path $SCENE/input \
  --output_path $SCENE/merge/sparse

echo
echo "################ 결과 ################"
python scripts/check_model.py $SCENE/merge/sparse
