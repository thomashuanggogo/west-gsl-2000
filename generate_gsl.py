import json
import asyncio
import aiohttp
import os
import sys
from deep_translator import GoogleTranslator

# 確保 Windows 下 print 中文不會有編碼問題
sys.stdout.reconfigure(encoding='utf-8')

DICT_API_URL = "https://api.dictionaryapi.dev/api/v2/entries/en/{}"
WORD_LIST_URL = "https://raw.githubusercontent.com/first20hours/google-10000-english/master/google-10000-english-no-swears.txt"
WORDS_JSON_PATH = "words.json"

translator_tw = GoogleTranslator(source='en', target='zh-TW')
translator_cn = GoogleTranslator(source='en', target='zh-CN')

async def fetch_word_data(session, word):
    try:
        async with session.get(DICT_API_URL.format(word), timeout=10) as response:
            if response.status != 200:
                return None
            data = await response.json()
            if not data or not isinstance(data, list):
                return None
            
            entry = data[0]
            phonetics = entry.get('phonetics', [])
            uk_pron = ""
            us_pron = ""
            for p in phonetics:
                if 'uk' in p.get('audio', '').lower():
                    uk_pron = p.get('text', '')
                if 'us' in p.get('audio', '').lower():
                    us_pron = p.get('text', '')
            
            if not uk_pron and not us_pron and phonetics:
                uk_pron = phonetics[0].get('text', '')
                us_pron = uk_pron
                
            meanings = entry.get('meanings', [])
            if not meanings:
                return None
            
            primary_meaning = meanings[0]
            word_type = primary_meaning.get('partOfSpeech', 'Noun').capitalize()
            
            definitions = primary_meaning.get('definitions', [])
            if not definitions:
                return None
                
            first_def = definitions[0]
            en_def = first_def.get('definition', '')
            en_ex = first_def.get('example', '')
            
            if not en_ex:
                en_ex = f"This is an example of {word}."

            return {
                "word": word,
                "type": word_type,
                "uk": uk_pron or f"/{word}/",
                "us": us_pron or f"/{word}/",
                "en_def": en_def,
                "en_ex": en_ex
            }
    except Exception as e:
        print(f"API 發生錯誤 {word}: {e}")
        return None

async def process_word(session, word):
    api_data = await fetch_word_data(session, word)
    if not api_data:
        print(f"  -> {word} 查無字典資料，跳過。")
        return None
    
    try:
        en_def = api_data['en_def']
        en_ex = api_data['en_ex']
        text_to_translate = f"{en_def} ||| {en_ex}"
        
        loop = asyncio.get_event_loop()
        translated_tw = await loop.run_in_executor(None, translator_tw.translate, text_to_translate)
        translated_cn = await loop.run_in_executor(None, translator_cn.translate, text_to_translate)
        
        tw_parts = translated_tw.split('|||')
        cn_parts = translated_cn.split('|||')
        
        tw_def = tw_parts[0].strip() if len(tw_parts) > 0 else en_def
        tw_ex = tw_parts[1].strip() if len(tw_parts) > 1 else en_ex
        
        cn_def = cn_parts[0].strip() if len(cn_parts) > 0 else en_def
        cn_ex = cn_parts[1].strip() if len(cn_parts) > 1 else en_ex

        print(f"  + 成功: {word}")
        return {
            "word": api_data['word'],
            "type": api_data['type'],
            "uk": api_data['uk'],
            "us": api_data['us'],
            "tw": tw_def,
            "cn": cn_def,
            "ex_en": en_ex,
            "ex_tw": tw_ex,
            "ex_cn": cn_ex
        }
    except Exception as e:
        print(f"  -> {word} 翻譯失敗: {e}")
        return None

async def main():
    print("啟動 GSL 全自動背景掛機抓取腳本 (Antigravity)")
    print("-" * 50)
    
    existing_data = []
    existing_words = set()
    if os.path.exists(WORDS_JSON_PATH):
        with open(WORDS_JSON_PATH, 'r', encoding='utf-8') as f:
            try:
                existing_data = json.load(f)
                existing_words = {w['word'].lower() for w in existing_data}
                print(f"已從 {WORDS_JSON_PATH} 讀取 {len(existing_data)} 個既有單字。")
            except json.JSONDecodeError:
                pass
                
    source_words = []
    if os.path.exists('gsl_source.txt'):
        with open('gsl_source.txt', 'r', encoding='utf-8') as f:
            source_words = [line.strip().lower() for line in f if line.strip() and len(line.strip()) > 2]
    else:
        async with aiohttp.ClientSession() as session:
            async with session.get(WORD_LIST_URL) as response:
                text = await response.text()
                source_words = [line.strip().lower() for line in text.split('\n') if line.strip() and len(line.strip()) > 2]
                source_words = source_words[:2000]
                
    words_to_fetch = [w for w in source_words if w not in existing_words]
    print(f"剩餘未擴充數量：{len(words_to_fetch)} 個單字。")
    
    if not words_to_fetch:
        print("全部 2000 個單字都已經抓取完畢！")
        return

    CHUNK_SIZE = 50
    total_new_entries = 0
    print(f"本次執行將自動抓取全部剩餘 {len(words_to_fetch)} 個單字，每抓 {CHUNK_SIZE} 個自動存檔一次以策安全...\\n")

    connector = aiohttp.TCPConnector(limit=5)
    async with aiohttp.ClientSession(connector=connector) as session:
        for i in range(0, len(words_to_fetch), CHUNK_SIZE):
            chunk = words_to_fetch[i:i + CHUNK_SIZE]
            print(f"\\n--- 正在處理第 {i+1} 到 {i+len(chunk)} 個單字 (共 {len(words_to_fetch)} 待處理) ---")
            
            tasks = [process_word(session, word) for word in chunk]
            results = await asyncio.gather(*tasks)
            
            new_entries = [r for r in results if r]
            if new_entries:
                existing_data.extend(new_entries)
                with open(WORDS_JSON_PATH, 'w', encoding='utf-8') as f:
                    json.dump(existing_data, f, ensure_ascii=False, indent=2)
                total_new_entries += len(new_entries)
                print(f"✅ 成功儲存 {len(new_entries)} 個單字。目前進度總庫存：{len(existing_data)} 詞。")
            
            if i + CHUNK_SIZE < len(words_to_fetch):
                print("⏳ 休息 3 秒避免觸發 API 限制...")
                await asyncio.sleep(3)
                
    print("-" * 50)
    print(f"✨ 執行完畢！本次總共成功擴充 {total_new_entries} 個單字。")

if __name__ == '__main__':
    asyncio.run(main())
