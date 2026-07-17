MAX_JOB_UPLOAD_FILES = 5000
MAX_MULTIPART_FORM_FIELDS = 1000


def too_many_files_detail(max_files: int = MAX_JOB_UPLOAD_FILES) -> str:
    return f"Too many files. Maximum number of files is {max_files}."
