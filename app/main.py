from typing import Annotated
from fastapi import FastAPI, File, UploadFile, HTTPException, BackgroundTasks, status
from fastapi.responses import FileResponse, StreamingResponse
import aiofiles

import os
import shutil
import io
import zipfile
from pathlib import Path
from enum import Enum

from src.entry import process_dir


class OmrTemplates(str, Enum):
    spm = "spm"


app = FastAPI()


@app.post("/upload_omr/{omr_template}")
async def upload_omr(
    files: Annotated[
        list[UploadFile], File(description="Multiple OMR image files to be processed")
    ],
    omr_template: OmrTemplates,
    status_code=status.HTTP_201_CREATED,
):
    allowed_file_extensions = [".jpg", ".png", ".jpeg"]
    file_extensions = set([Path(file.filename).suffix for file in files])

    if not file_extensions.issubset(allowed_file_extensions):
        raise HTTPException(
            422, detail="Invalid document type. Only (*.png, *.jpg, *.jpeg) are allowed"
        )
    await save_files_to(files, omr_template)

    return {"filenames": [file.filename for file in files]}


async def save_files_to(files: list[UploadFile], omr_template: OmrTemplates):
    os.mkdir(os.path.join("inputs/", omr_template.value, "images/"))
    save_dir_path = os.path.join("inputs/", omr_template.value, "images/")
    for file in files:
        save_file_path = os.path.join(save_dir_path, file.filename)
        async with aiofiles.open(save_file_path, "wb") as out_file:
            while content := await file.read(1024):  # async read chunk
                await out_file.write(content)  # async write chunk


@app.get("/process_omr/{omr_template}", response_class=FileResponse)
async def process_omr(
    omr_template: OmrTemplates,
    background_tasks: BackgroundTasks,
    show_image_results: bool = False,
):
    process_dir_path = os.path.join("inputs/", omr_template.value)
    process_args = {
        "input_paths": [process_dir_path],
        "debug": False,
        "output_dir": "outputs/spm",
        "autoAlign": False,
        "setLayout": False,
    }

    process_img_dir_path = os.path.join(process_dir_path, "images/")
    if (not os.path.isdir(process_img_dir_path)) or (
        not os.listdir(process_img_dir_path)
    ):
        raise HTTPException(
            400,
            detail=f"No OMR images for {omr_template.value} in queue to be processed",
        )

    try:
        process_dir(Path(process_dir_path), Path(process_dir_path), process_args)
    except Exception as e:
        raise HTTPException(500, detail=e)

    output_root_dir = os.path.join("outputs/", omr_template.value, "images/")

    zip_bytes_io = io.BytesIO()
    with zipfile.ZipFile(zip_bytes_io, "w", zipfile.ZIP_DEFLATED) as zipped:
        cwd = os.getcwd()
        os.chdir(output_root_dir)

        for dirname, subdirs, files in os.walk("."):
            if not show_image_results and "CheckedOMRs" in dirname:
                continue
            zipped.write(dirname)
            for filename in files:
                zipped.write(os.path.join(dirname, filename))

        os.chdir(cwd)

    response = StreamingResponse(
        iter([zip_bytes_io.getvalue()]),
        media_type="application/x-zip-compressed",
        headers={
            "Content-Disposition": f"attachment;filename={omr_template.value}_output.zip",
            "Content-Length": str(zip_bytes_io.getbuffer().nbytes),
        },
    )
    zip_bytes_io.close()

    background_tasks.add_task(delete_processed_files, omr_template)

    return response


def delete_processed_files(omr_template: OmrTemplates):
    try:
        delete_processed_inputs_path = os.path.join(
            "inputs/", omr_template.value, "images/"
        )
        shutil.rmtree(delete_processed_inputs_path)

        delete_processed_outputs_path = os.path.join("outputs/", omr_template.value)
        shutil.rmtree(delete_processed_outputs_path)

    except shutil.Error:
        raise HTTPException(
            500, detail="Error occurred while deleting processed output files"
        )


# async def verify_output(omr_template: OmrTemplates):
#     output_root_dir = os.path.join("outputs/", omr_template.value)
#     error_files = False
#     multi_marked_files = False
#
#     if os.listdir(os.path.join(output_root_dir, "Manual/", "ErrorFiles")):
#         error_files = True
#
#     if os.listdir(os.path.join(output_root_dir, "Manual/", "MultiMarkedFiles")):
#         multi_marked_files = True
#
#     return error_files, multi_marked_files
