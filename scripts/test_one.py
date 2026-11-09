import torch
from transformers import AutoModelForCausalLM, AutoTokenizer
for path in ["models/v1", "models/v2"]:
    tok = AutoTokenizer.from_pretrained(path)
    model = AutoModelForCausalLM.from_pretrained(path, dtype=torch.float32)
    model.eval()
    prompt = "Command: remove the upcoming calendar event JSON:"
    inputs = tok(prompt, return_tensors="pt")
    print(path, "prompt tokens:", tok.convert_ids_to_tokens(inputs["input_ids"][0].tolist()))
    with torch.no_grad():
        out = model.generate(**inputs, max_new_tokens=20, do_sample=False, pad_token_id=tok.pad_token_id)
        logits = model(**inputs).logits[0, -1]
        top = torch.topk(logits, 5)
    gen_ids = out[0][inputs["input_ids"].shape[1]:].tolist()
    print(path, "generated ids:", gen_ids)
    print(path, "generated tokens:", tok.convert_ids_to_tokens(gen_ids))
    print(path, "generated text:", repr(tok.decode(gen_ids, skip_special_tokens=False)))
    print(path, "top5 next tokens after prompt:", [(tok.decode([i]), round(float(v),2)) for v,i in zip(top.values, top.indices)])
    print()
