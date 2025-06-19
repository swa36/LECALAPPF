import os
import shutil

def copy_and_split_jpg():
    source_dir = "media/img"
    base_target_dir = "media/all_img"
    os.makedirs(base_target_dir, exist_ok=True)

    batch_size = 1000
    batch_index = 1
    file_count = 0

    current_target_dir = os.path.join(base_target_dir, f"batch_{batch_index}")
    os.makedirs(current_target_dir, exist_ok=True)

    for folder in sorted(os.listdir(source_dir)):  # сортировка для стабильности
        folder_path = os.path.join(source_dir, folder)
        if not os.path.isdir(folder_path):
            continue

        # Соберём все файлы, которые будут скопированы из текущей папки
        files_to_copy = []
        for file in os.listdir(folder_path):
            file_path = os.path.join(folder_path, file)
            if not os.path.isfile(file_path):
                continue

            if file == "main.jpg":
                new_name = f"{folder}.jpg"
            elif file.endswith(".jpg") and file[:-4].isdigit():
                new_name = f"{folder}_{file}"
            else:
                continue

            files_to_copy.append((file_path, new_name))

        # Если добавление всех файлов из папки превышает лимит — начни новую папку
        if file_count + len(files_to_copy) > batch_size:
            batch_index += 1
            file_count = 0
            current_target_dir = os.path.join(base_target_dir, f"batch_{batch_index}")
            os.makedirs(current_target_dir, exist_ok=True)

        # Копируем файлы
        for src_path, new_name in files_to_copy:
            dst_path = os.path.join(current_target_dir, new_name)
            shutil.copy2(src_path, dst_path)
            print(f"✔ Скопировано: {src_path} → {dst_path}")
            file_count += 1

copy_and_split_jpg()
