from pathlib import Path
import shutil
import pandas as pd
from typing import List, Optional, Dict
import os

from .plugin import Plugin
from .results import Results, ExecInfo
from .fileutils import PathLike
from .parameters import Parameters
from .template import TemplateRenderer
import subprocess



class ResultsALEAF(Results):
    """ALEAF simulation results."""

    def __init__(self, params: Parameters, exec_info: ExecInfo,
                 inputs: List[PathLike], outputs: List[PathLike]):
        super().__init__(params, exec_info, inputs, outputs)
        self.csv_data = self._get_aleaf_csv_data()

    def _get_aleaf_csv_data(self) -> pd.DataFrame:
        """Read ALEAF output CSV file and return results as a DataFrame."""
        output_file = next((p for p in self.outputs if p.name.endswith('_system_tech_summary_EXP.csv')), None)
        if output_file and output_file.exists():
            return pd.read_csv(output_file)
        else:
            return pd.DataFrame()  # Return an empty DataFrame if no CSV file is found


class PluginALEAF(Plugin):
    """Plugin for running ALEAF."""

    def __init__(self, template_file: PathLike, extra_templates: Optional[Dict[str, PathLike]] = None,
                 show_stdout: bool = False, show_stderr: bool = False):
        super().__init__(extra_inputs=[], show_stdout=show_stdout, show_stderr=show_stderr)
        self.template_file = template_file
        self.extra_templates = extra_templates or {}
        self.plugin_name = 'ALEAF'
        self.renderer = TemplateRenderer(template_file)
        self.aleaf_dir = os.getenv('ALEAF_DIR')
        if not self.aleaf_dir:
            raise EnvironmentError("ALEAF_DIR environment variable is not set.")
        self.output_folder = None

    def prerun(self, params: Parameters) -> None:
        """Generate ALEAF input files and check for pre-existing output."""

        # Copy the original ALEAF input file to the working directory
        original_input_path = Path(self.aleaf_dir) / "setting/ALEAF_Master_LC_GTEP.xlsx"
        modified_input_path = Path("ALEAF_Master_LC_GTEP.xlsx")
        shutil.copy(original_input_path, modified_input_path)

        # Load the Excel file and modify the 'Fuel' sheet
        fuel_data = self.renderer(params)

        with pd.ExcelWriter(modified_input_path, engine='openpyxl', mode='a', if_sheet_exists='replace') as writer:
            fuel_sheet = pd.read_excel(writer, sheet_name='Fuel')
            fuel_sheet.update(fuel_data)
            fuel_sheet.to_excel(writer, sheet_name='Fuel', index=False)

        # Render and apply additional templates if provided
        for sheet_name, template_path in self.extra_templates.items():
            template_renderer = TemplateRenderer(template_path)
            sheet_data = template_renderer(params)
            with pd.ExcelWriter(modified_input_path, engine='openpyxl', mode='a', if_sheet_exists='replace') as writer:
                sheet_data.to_excel(writer, sheet_name=sheet_name, index=False)

        # Copy the modified input file back to the original directory in ALEAF_DIR
        shutil.copy(modified_input_path, original_input_path)

        # Check the 'Simulation Configuration' sheet to find the correct case and CaseID remove the first row
        config_sheet = pd.read_excel(modified_input_path, sheet_name='Simulation Configuration', header=1)
        # Find the row with Run_Flag set to TRUE
        case_row = config_sheet[config_sheet['Run_Flag'] == True].iloc[0]
        case_id = case_row['Case_ID']
        # Build the expected output directory and file path based on CaseID
        output_folder = Path(self.aleaf_dir) / f"output/LC_GTEP/USA/case_id_{case_row.name+1}_{case_id}"
        output_file = output_folder / f"{case_id}__system_tech_summary_EXP.csv"

        # If the output file exists, back it up or delete it before running a new simulation
        if output_file.exists():
            backup_folder = output_folder / "backup"
            backup_folder.mkdir(parents=True, exist_ok=True)
            shutil.move(str(output_file), backup_folder / output_file.name)

        # Save the output folder path for later use in postrun
        self.output_folder = output_folder


    def run(self):
        """Run ALEAF."""
        command = ['julia', 'execute_ALEAF.jl']
        subprocess.run(command, cwd=self.aleaf_dir)

    def postrun(self, params: Parameters, exec_info: ExecInfo) -> ResultsALEAF:
        """Collect information from ALEAF simulation and create results object."""
        output_folder = Path(self.aleaf_dir) / f"output/LC_GTEP/USA/case_id_1_Test EXP"
        outputs = [output_folder / "Test EXP__system_tech_summary_EXP.csv"]
        return ResultsALEAF(params, exec_info, self.extra_inputs, outputs)
