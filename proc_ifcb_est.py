#!/home/jqwu/anaconda3/bin/python3
from funcs import gnss_tools as gt, gnss_run as gr
from proc_gen import ProcGen
import os
import logging


class ProcIfcb(ProcGen):
    def __init__(self):
        super().__init__()

        self.default_args['dsc'] = "GREAT IFCB Estimation"
        self.default_args['intv'] = 30
        self.default_args['freq'] = 3
        self.default_args['obs_comb'] = 'UC'
        self.default_args['cf'] = 'cf_upd.ini'

        self.required_opt = ['estimator']
        self.required_file = ['rinexo', 'biabern']

    def update_path(self, all_path):
        super().update_path(all_path)
        self.proj_dir = os.path.join(self.config.config['common']['base_dir'], 'UPD')

    def process_daily(self):
        logging.info(f"------------------------------------------------------------------------")
        logging.info(f"Everything is ready: number of stations = {len(self.config.stalist())}, "
                     f"number of satellites = {len(self.config.all_gnssat())}")

        with gt.timeblock("Finished IFCB estimation"):
            gr.run_great(self.grt_bin, 'great_updlsq', self.config, mode='ifcb', label='ifcb', xmldir=self.xml_dir)

        upd_data = self.config.config.get("common", "upd_data")
        logging.info(f"===> Copy UPD results to {upd_data}")
        gt.copy_result_files_to_path(self.config, ['ifcb'], os.path.join(upd_data, f"{self.config.beg_time().year}"))


if __name__ == '__main__':
    proc = ProcIfcb()
    proc.process_batch()
