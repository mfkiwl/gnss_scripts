import os
import sys
import shutil
import logging
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from app_gnss.proc_gen import ProcGen
from funcs import timeblock, copy_result_files, copy_result_files_to_path, \
    recover_files, check_pod_residuals, check_pod_residuals_new, check_pod_sigma, backup_dir, check_ics, \
    GrtOrbdif, GrtClkdif, GrtPodlsq, GrtOi, GrtOrbsp3, GrtAmbfix


class ProcPod(ProcGen):
    default_args = {
        'dsc': 'GREAT GNSS Precise Orbit Determination',
        'num': 1, 'seslen': 24, 'intv': 300, 'obs_comb': 'IF', 'est': 'LSQ', 'sys': 'G',
        'freq': 2, 'cen': 'com', 'bia': '', 'cf': 'cf_pod.ini'
    }

    proj_id = 'POD'

    required_subdir = super().required_subdir + ['orbdif', 'clkdif']
    required_opt = super().required_opt + ['estimator']
    required_file = super().required_file + ['rinexo', 'rinexn', 'biabern']

    ref_cen = ['com', 'gbm', 'wum', 'esm']
    sat_rm = ['C01', 'C02', 'C03', 'C04', 'C05', 'C59', 'C60',
              'C39', 'C40', 'C41', 'C42', 'C43', 'C44', 'C45', 'C46']

    def prepare(self):
        with timeblock('Finished prepare ics'):
            if not self.prepare_ics():
                return False
        return super().prepare()

    def orbdif(self, label=''):
        for c in self.ref_cen:
            self._config.orb_ac = c
            GrtOrbdif(self._config, f'orbdif_{c}').run()
            if label:
                copy_result_files(self._config, ['orbdif'], label, 'gns')
            for g in self._gsys:
                self._config.gsys = g
                GrtClkdif(self._config, f'clkdif_{c}_{g}').run()
                if label:
                    copy_result_files(self._config, ['clkdif'], label, 'gns')
            self._config.gsys = self._gsys

    def generate_products(self, label=''):
        GrtOrbsp3(self._config, 'orbsp3').run()
        f_sp31 = self._config.get_xml_file('sp3_out', check=True)
        f_clk0 = self._config.get_xml_file('satclk', check=True)
        f_clk1 = self._config.get_xml_file('clk_out', check=False)
        if f_clk0:
            shutil.copy(f_clk0[0], f_clk1[0])
        if label:
            if f_sp31:
                shutil.copy(f_sp31[0], f"{f_sp31[0]}_{label}")
            if os.path.isfile(f_clk1[0]):
                shutil.copy(f_clk1[0], f"{f_clk1[0]}_{label}")

    def detect_outliers(self):
        for i in range(10):
            GrtPodlsq(self._config, 'podlsq', str_args='-brdm').run()
            if i > 0 and check_pod_sigma(self._config, maxsig=10):
                return True
            bad_site, bad_sat = check_pod_residuals_new(self._config)
            if not bad_site and not bad_sat:
                break
            recover_files(self._config, ['ics', 'orb'])
            self._config.remove_site(bad_site)
            if bad_sat:
                logging.warning(f"SATELLITES {' '.join(bad_sat)} are removed")
            self._config.sat_rm += bad_sat
            logging.info(f"reprocess-{i+1} great_podlsq due to bad stations or satellites")
        return True

    def process_orb(self, label='F1', eval=True, prod=False):
        GrtOi(self._config, 'oi').run()
        if eval:
            self.orbdif(label)
        if prod:
            self.generate_products(label)

    def process_1st_pod(self, label='F1', eval=True, prod=False):
        check_ics(self._config)
        if not self.detect_outliers():
            logging.error("podlsq wrong!")
            return False
        if not check_pod_sigma(self._config, maxsig=200):
            return False
        self.process_orb(label, eval, prod)
        return True

    def process_float_pod(self, label='F2', eval=True, prod=False):
        GrtPodlsq(self._config, 'podlsq').run()
        if not check_pod_sigma(self._config, maxsig=200):
            return False
        self.process_orb(label, eval, prod)
        return True

    def process_fix_pod(self, label='AR', eval=True, prod=True):
        GrtPodlsq(self._config, 'podlsq_fix', fix_amb=True, use_res_crd=True).run()
        if not check_pod_sigma(self._config, maxsig=200):
            return False
        self.process_orb(label, eval, prod)
        return True

    # todo: ambfix is not work for UC model
    def process_ambfix(self):
        self._config.intv = 30
        GrtAmbfix(self._config, "DD", 'ambfix').run()
        # GrtAmbfixDd(self._config, 'ambfix').run()
        self._config.intv = self._intv

    def save_results(self, labels):
        result_dir = self._config.file_name('result_dir')
        if not result_dir:
            return
        orbdif_dir = os.path.join(result_dir, "orbdif", f"{self._config.beg_time.year}")
        clkdif_dir = os.path.join(result_dir, "clkdif", f"{self._config.beg_time.year}")
        for c in self.ref_cen:
            self._config.orb_ac = c
            copy_result_files_to_path(self._config, ['orbdif'], orbdif_dir, labels)
            for g in self._gsys:
                self._config.gsys = g
                copy_result_files_to_path(self._config, ['clkdif'], clkdif_dir, labels)
            self._config.gsys = self._gsys

    def process_daily(self):
        logging.info(f"------------------------------------------------------------------------\n{' '*36}"
                     f"Everything is ready: number of stations = {len(self._config.site_list)}, "
                     f"number of satellites = {len(self._config.all_gnssat)}")
        logging.info(f"===> 1st iteration for precise orbit determination")
        with timeblock("Finished 1st POD"):
            if not self.process_1st_pod('F1', True, False):
                return
            backup_dir('log_tb', 'log_tb_orig')
            self.editres(bad=80, jump=80, nshort=600)
            if not self.basic_check(files=['ambflag']):
                logging.error('process POD failed! no valid ambflag file')
                return
            copy_result_files(self._config, ['recover'], 'F1')

        logging.info(f"===> 2nd iteration for precise orbit determination")
        with timeblock("Finished 2nd POD"):
            if not self.process_float_pod('F2', True, False):
                return
            self.editres(bad=40, jump=40, nshort=600)
            copy_result_files(self._config, ['recover'], 'F2')

        logging.info(f"===> 3rd iteration for precise orbit determination")
        with timeblock('Finished 3rd POD'):
            if not self.process_float_pod('F3', True, True):
                return
            copy_result_files(self._config, ['ics', 'orb', 'satclk', 'recclk', 'recover'], 'F3')

        logging.info(f"===> 4th iteration for precise orbit determination")
        with timeblock('Finished fixed POD'):
            self.process_ambfix()
            if not self.process_fix_pod('AR', True, True):
                return
            copy_result_files(self._config, ['ics', 'orb', 'satclk', 'recclk', 'recover'], 'AR')
        
        self.save_results(['F3', 'AR'])


if __name__ == '__main__':
    proc = ProcPod.from_args()
    proc.process_batch()
