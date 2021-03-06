from data import PretrainingDataset, collate_missing, cycle
from transformer import FaceTransformer, CosineWithRestarts
import torch
from torch.utils.data import DataLoader
from pathlib import Path
import time
from data import SPECIAL_TOKENS

timestamp = str(int(time.time()))

root_dir = "/media/quadserver2/data/paul/face/AVSpeech/FaceKeypointsCPU2/"
clips_list = "/media/quadserver2/data/paul/face/AVSpeech/filter_clips.txt"
save_dir = "/media/quadserver2/data/paul/face/face-transformer/checkpoints/"

dataset = PretrainingDataset(root_dir, clips_list)
dataloader = cycle(DataLoader(
    dataset,
    batch_size=500,
    shuffle=False,
    num_workers=1
))

device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
model = FaceTransformer(68).to(device)
model = torch.nn.DataParallel(model).to(device)

criterion_mask = torch.nn.MSELoss()
criterion_nsp = torch.nn.CrossEntropyLoss()
num_batches = 50000
accum_steps = 4
save_every = 99
restart_every = 1000
lr = 1e-1
optimizer = torch.optim.AdamW(model.parameters(), lr=lr, betas=(0.9, 0.98), eps=1e-9)
sched = CosineWithRestarts(optimizer, T_max=restart_every)

for i in range(num_batches):
    model.train()
    batch_loss = 0
    for __ in range(accum_steps):
        arrays, special_mask, nsp_labels = next(dataloader)
        mask_labels = arrays[special_mask == SPECIAL_TOKENS['MASK']]
        
        triu = torch.triu_indices(68, 68, offset=1, device=mask_labels.device)
        mask_labels = torch.linalg.norm(mask_labels[..., None, :] - mask_labels[..., None, :, :], dim=-1, ord=2)
        mask_labels = mask_labels[:,triu[0],triu[1]]

        mask_preds, nsp_preds = model(arrays.to(device), special_mask.to(device))
        loss_dist = criterion_mask(mask_preds.cpu(), mask_labels)
        loss_nsp = criterion_nsp(nsp_preds.cpu(), nsp_labels)
        loss = loss_dist + loss_nsp
        batch_loss += loss.item()
        loss.backward()

    torch.nn.utils.clip_grad_norm_(model.parameters(), 0.5)
    optimizer.step()
    sched.step()
    optimizer.zero_grad()

    if i == 0 or (((i+1) % save_every) == 0):
        torch.save(model.module.state_dict(), Path(save_dir, F"v2-{timestamp}-batch-{i+1}.ckpt"))

    print(F"batch {i}, loss {batch_loss}")
