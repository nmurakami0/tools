#!/usr/bin/env python3
import argparse
import os

from openai import OpenAI

# tiktokenがインストールされていれば利用。なければ簡易計算を行う。
try:
    import tiktoken
except ImportError:
    tiktoken = None
    print("tiktokenがインストールされていません。トークン数のカウントは簡易計算で行います。")

def split_text_by_tokens(text, max_tokens_per_segment, model="gpt-4o-mini"):
    """
    入力テキストをトークン数に基づいてセグメントに分割する関数。
    Whisperの文字起こしファイルは改行ごとに分割し、
    セグメントが max_tokens_per_segment を超えたら改段する。
    """
    segments = []
    current_segment = ""

    if tiktoken:
        encoding = tiktoken.encoding_for_model(model)
        def count_tokens(s):
            c = len(encoding.encode(s))
            print(f"トークン数: {c}")
            return c
    else:
        # おおよその推定：1トークン＝約4文字
        def count_tokens(s):
            c = len(s) // 4
            print(f"トークン数: {c}")
            return c

    for line in text.split(" "):
        if not line.strip():
            continue  # 空行はスキップ
        # 現在のセグメントにこの行を追加した場合のトークン数が上限を超えるか確認
        if count_tokens(current_segment + line) > max_tokens_per_segment:
            segments.append(current_segment)
            current_segment = line + "\n"
        else:
            current_segment += line + "\n"
    if current_segment:
        segments.append(current_segment)
    return segments

def format_segment(client, segment, model="gpt-4o-mini", temperature=0.3):
    """
    OpenAI APIを使って、セグメントの文章を読みやすい日本語に整形する関数。
    systemプロンプトで「プロの編集者」としての役割を与え、user側で整形依頼を行います。
    """
    prompt = f"以下は会議の音声を文字起こしした結果です。適度に改行の追加や段落分けをして見やすい文章に直してください。誤字脱字も修正してください。整形した文章以外は出力に含めないでください。:\n\n{segment}"
    messages = [
        {"role": "system", "content": "あなたはプロの編集者です。"},
        {"role": "user", "content": prompt}
    ]
    try:
        response = client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature,
        )
    except Exception as e:
        print("API呼び出し中にエラーが発生しました:", e)
        raise e
    formatted_text = response.choices[0].message.content.strip()
    return formatted_text

def main(client, input_file, output_file, max_tokens_per_segment=8000, model="gpt-4o-mini"):
    # 1. 入力ファイルの読み込み
    with open(input_file, "r", encoding="utf-8") as f:
        text = f.read()

    # 2. テキストをセグメントに分割（コンテキストウィンドウに合わせる）
    segments = split_text_by_tokens(text, max_tokens_per_segment, model=model)
    print(f"全{len(segments)}セグメントに分割しました。")

    formatted_segments = []
    # 3. 各セグメントをOpenAI APIで整形
    for i, segment in enumerate(segments):
        print(f"セグメント {i+1}/{len(segments)} を整形中...")
        formatted_text = format_segment(client, segment, model=model)
        formatted_segments.append(formatted_text)

    # 4. 整形済みセグメントを統合し、出力ファイルに保存
    final_text = "\n\n".join(formatted_segments)
    with open(output_file, "w", encoding="utf-8") as f:
        f.write(final_text)
    print(f"整形した文章を {output_file} に保存しました。")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Whisperの文字起こしファイルを読みやすく整形するスクリプト"
    )
    parser.add_argument("input_file", help="入力テキストファイルのパス")
    parser.add_argument("output_file", help="出力ファイルのパス")
    parser.add_argument("--max_tokens", type=int, default=8000, help="セグメントごとの最大トークン数")
    parser.add_argument("--model", type=str, default="gpt-4o-mini", help="使用するOpenAIモデル")
    args = parser.parse_args()

    client = OpenAI(
    api_key=os.environ.get("OPENAI_API_KEY"),  # This is the default and can be omitted
    )
    main(client, args.input_file, args.output_file, max_tokens_per_segment=args.max_tokens, model=args.model)

